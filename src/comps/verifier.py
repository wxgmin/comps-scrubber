from __future__ import annotations

import re
from typing import Optional

from .models import Adjustment, Flag

# Category -> candidate us-gaap tags for the XBRL cross-check.
XBRL_TAGS: dict[str, list[str]] = {
    "Restructuring": [
        "RestructuringCharges",
        "RestructuringCostsAndAssetImpairmentCharges",
        "RestructuringSettlementAndImpairmentProvisions",
    ],
    "Impairment": [
        "AssetImpairmentCharges",
        "GoodwillImpairmentLoss",
        "ImpairmentOfIntangibleAssetsExcludingGoodwill",
    ],
    "Litigation": [
        "LitigationSettlementExpense",
        "GainLossRelatedToLitigationSettlement",
    ],
    "M&A_Transaction": [
        "BusinessCombinationAcquisitionRelatedCosts",
        "AcquisitionRelatedCosts",
    ],
    "Asset_Sale": [
        "GainLossOnSaleOfBusiness",
        "GainLossOnDispositionOfAssets",
        "GainLossOnSaleOfAssets",
        "DisposalGroupNotDiscontinuedOperationGainLossOnDisposal",
    ],
    "StockBasedCompensation": [
        "ShareBasedCompensation",
        "AllocatedShareBasedCompensationExpense",
        "ShareBasedCompensationCost",
    ],
}

_NUMBER_RE = re.compile(
    r"(?<![\w.])-?\$?\s*([\d,]+(?:\.\d+)?)\s*(billion|bn|million|mm|thousand|k)?",
    re.IGNORECASE,
)


def normalize(text: Optional[str]) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip().lower()


def _normalize_lenient(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", normalize(text))


def quote_matches(quote: str, text: str) -> bool:
    """Verbatim check: the quoted sentence must appear in the source text."""
    if not quote or not text:
        return False
    if normalize(quote) in normalize(text):
        return True
    # fallback: ignore punctuation/case/whitespace differences
    return _normalize_lenient(quote) in _normalize_lenient(text) if len(quote) >= 12 else False


def extract_numbers(text: str) -> list[tuple[float, float]]:
    """Return (value, multiplier) pairs for every number + scale word in `text`."""
    out: list[tuple[float, float]] = []
    for m in _NUMBER_RE.finditer(text):
        raw = m.group(1).replace(",", "")
        try:
            val = float(raw)
        except ValueError:
            continue
        scale = (m.group(2) or "").lower()
        mult = 1.0
        if scale in ("billion", "bn"):
            mult = 1e9
        elif scale in ("million", "mm"):
            mult = 1e6
        elif scale in ("thousand", "k"):
            mult = 1e3
        out.append((val, mult))
    return out


def _close(a: float, b: float, rel: float = 0.02) -> bool:
    if b == 0:
        return abs(a) < 1.0
    return abs(a - b) <= max(1.0, rel * abs(b))


def amount_in_quote(amount: float, quote: str) -> bool:
    """The amount must be recoverable from digits + scale in the exact quoted sentence.

    Tolerates a table/unit header that lives outside the quote (e.g. the quote says
    "restructuring charges: 18,639" while a separate header says "in thousands").
    """
    if amount is None or not quote:
        return False
    pairs = extract_numbers(quote)
    if not pairs:
        return False
    for val, mult in pairs:
        candidate = val * mult
        if _close(amount, candidate):
            return True
        for pow10 in (1e3, 1e6, 1e9):
            if _close(amount, candidate * pow10) or _close(amount, candidate / pow10):
                return True
    return False


def verify_adjustment(
    adj: Adjustment,
    tenk_text: str,
    earnings_text: str,
    sec_client,
    companyfacts: dict,
) -> Flag | None:
    """Verify one adjustment against its sources. Mutates adj; returns a Flag if rejected."""
    source = tenk_text if adj.source_document == "10-K" else earnings_text

    if not quote_matches(adj.source_quote, source):
        adj.verification_status = "quote_not_found"
        return Flag(
            ticker="",
            fy_end=adj.fy_end,
            category=adj.category,
            reason="quote_not_found",
            detail=adj.source_quote[:160],
        )

    if not amount_in_quote(adj.amount, adj.source_quote):
        adj.verification_status = "amount_not_in_quote"
        return Flag(
            ticker="",
            fy_end=adj.fy_end,
            category=adj.category,
            reason="amount_not_in_quote",
            detail=f"{adj.amount:,.0f} :: {adj.source_quote[:160]}",
        )

    # XBRL cross-check is a secondary confirmation, not a hard gate (the quote is
    # authoritative for the amount).
    for tag in XBRL_TAGS.get(adj.category, []):
        v = sec_client.xbrl_value(companyfacts, tag, adj.fy_end)
        if v is not None:
            adj.xbrl_match = v
            if _close(abs(v), adj.amount, rel=0.05):
                adj.verification_status = "ok_xbrl"
            elif _close(abs(v), adj.amount, rel=0.25):
                adj.verification_status = "ok_xbrl_soft"
            else:
                adj.verification_status = "xbrl_mismatch"
            break
    else:
        adj.verification_status = adj.verification_status or "ok"

    adj.verified = adj.verification_status in ("ok", "ok_xbrl", "ok_xbrl_soft", "xbrl_mismatch")
    return None


def foot_bridge(reported_ebitda: Optional[float], adjustments: list[Adjustment]) -> Optional[float]:
    if reported_ebitda is None:
        return None
    return reported_ebitda + sum(a.signed_amount for a in adjustments)
