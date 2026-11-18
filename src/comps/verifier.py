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

# GainLoss* tags are directional in GAAP: a positive value is a gain, negative is a loss.
DIRECTIONAL_TAGS = {
    "GainLossOnSaleOfBusiness",
    "GainLossOnDispositionOfAssets",
    "GainLossOnSaleOfAssets",
    "DisposalGroupNotDiscontinuedOperationGainLossOnDisposal",
    "GainLossRelatedToLitigationSettlement",
}

_MIN_QUOTE_ALNUM = 12

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
    """Verbatim check: the quoted sentence must appear in the source text.

    Requires a minimum alphanumeric length so a one- or two-token quote cannot
    trivially "match" everywhere.
    """
    if not quote or not text:
        return False
    compact = _normalize_lenient(quote)
    if len(compact) < _MIN_QUOTE_ALNUM:
        return False
    if normalize(quote) in normalize(text):
        return True
    # fallback: ignore punctuation/case/whitespace differences
    return compact in _normalize_lenient(text)


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

    Tolerates a unit header that lives outside the quote (e.g. the quote says
    "restructuring charges: 18,639" while a separate table header says "in thousands"
    or "in millions"). That fallback is applied ONLY when the number carries no explicit
    scale word, and only for the two common header units (thousands, millions).
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
        if mult == 1.0:  # no explicit scale word -> tolerate a unit header
            if _close(amount, candidate * 1e3) or _close(amount, candidate * 1e6):
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
        adj.verified = False
        return Flag(
            ticker="",
            fy_end=adj.fy_end,
            category=adj.category,
            reason="quote_not_found",
            detail=adj.source_quote[:160],
        )

    if not amount_in_quote(adj.amount, adj.source_quote):
        adj.verification_status = "amount_not_in_quote"
        adj.verified = False
        return Flag(
            ticker="",
            fy_end=adj.fy_end,
            category=adj.category,
            reason="amount_not_in_quote",
            detail=f"{adj.amount:,.0f} :: {adj.source_quote[:160]}",
        )

    # XBRL cross-check: confirm magnitude and, for directional tags, direction.
    for tag in XBRL_TAGS.get(adj.category, []):
        v = sec_client.xbrl_value(companyfacts, tag, adj.fy_end)
        if v is None:
            continue
        adj.xbrl_match = v  # signed (gain > 0, loss < 0 for GainLoss* tags)
        mag = abs(v)
        if _close(mag, adj.amount, rel=0.05):
            adj.verification_status = "ok_xbrl"
        elif _close(mag, adj.amount, rel=0.25):
            adj.verification_status = "ok_xbrl_soft"
        else:
            adj.verification_status = "xbrl_mismatch"
        if tag in DIRECTIONAL_TAGS and v != 0:
            expected = "subtract" if v > 0 else "add_back"
            if adj.sign != expected:
                adj.sign_conflict = True
        break
    else:
        adj.verification_status = "ok"

    # A gross (>25%) discrepancy against the independent XBRL tag needs human review.
    if adj.verification_status == "xbrl_mismatch":
        adj.verified = False
        return Flag(
            ticker="",
            fy_end=adj.fy_end,
            category=adj.category,
            reason="xbrl_mismatch",
            detail=f"quote={adj.amount:,.0f} xbrl={adj.xbrl_match:,.0f}",
        )

    adj.verified = True
    return None


def foot_bridge(reported_ebitda: Optional[float], adjustments: list[Adjustment]) -> Optional[float]:
    if reported_ebitda is None:
        return None
    return reported_ebitda + sum(a.signed_amount for a in adjustments)
