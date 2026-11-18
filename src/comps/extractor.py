from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Optional

from .config import CACHE_DIR
from .llm import extract_json
from .models import Adjustment, ExtractionResult, ReportedAdjustedEbitda, CATEGORIES

KEYWORDS = [
    "restructuring",
    "impairment",
    "litigation",
    "acquisition",
    "disposal",
    "divestiture",
    "stock-based compensation",
    "stock based compensation",
    "non-gaap",
    "non gaap",
    "adjusted ebitda",
    "adjusted",
    "nonrecurring",
    "non-recurring",
    "severance",
    "settlement",
    "gain on",
    "loss on",
    "transaction costs",
    "integration",
]

_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["company_reported_adjusted_ebitda", "adjustments"],
    "properties": {
        "company_reported_adjusted_ebitda": {
            "type": "object",
            "additionalProperties": False,
            "required": ["amount", "source_quote", "source_doc"],
            "properties": {
                "amount": {"type": ["number", "null"]},
                "source_quote": {"type": "string"},
                "source_doc": {"type": "string", "enum": ["8-K_99.1", "10-K"]},
            },
        },
        "adjustments": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "category",
                    "amount",
                    "sign",
                    "source_quote",
                    "source_document",
                    "source_section",
                    "is_recurring",
                    "confidence",
                    "rationale",
                ],
                "properties": {
                    "category": {"type": "string", "enum": CATEGORIES},
                    "amount": {"type": "number"},
                    "sign": {"type": "string", "enum": ["add_back", "subtract"]},
                    "source_quote": {"type": "string"},
                    "source_document": {"type": "string", "enum": ["10-K", "8-K_99.1"]},
                    "source_section": {"type": "string"},
                    "is_recurring": {"type": "boolean"},
                    "confidence": {"type": "number"},
                    "rationale": {"type": "string"},
                },
            },
        },
    },
}

_SYSTEM = """You are a financial analyst extracting non-recurring items from SEC filings for an \
EBITDA adjustment bridge. Every number you report MUST be traceable: the `source_quote` must be \
the verbatim sentence (or table row) from the source that contains the number. Never invent or \
infer an amount — if a number is not stated in the source, do not include the item.

Rules:
- `amount` is the ABSOLUTE value expressed in US dollars (multiply out any "thousands" or \
"millions" stated in the source or its table header).
- `sign` is "add_back" when the item is a cost/expense/loss that reduced reported earnings, \
and "subtract" when it is a gain/income that inflated reported earnings.
- Only include items that a standard comps adjustment policy would scrub: restructuring, \
impairments, litigation settlements, M&A transaction/integration costs, gains/losses on asset \
sales, and stock-based compensation. Do NOT include ordinary recurring operating costs.
- Set `is_recurring` true if the same item appears in every fiscal year (e.g. annual \
"restructuring" that is really ordinary severance).
- `company_reported_adjusted_ebitda` is the company's OWN reported adjusted EBITDA (from its \
non-GAAP reconciliation). If the company does not disclose one, use amount null and an empty \
source_quote."""

# Bump-cache key: changing the prompt, schema, or keywords invalidates cached extractions.
_CACHE_VERSION = hashlib.sha1(
    (_SYSTEM + json.dumps(_SCHEMA, sort_keys=True) + "|".join(KEYWORDS)).encode("utf-8")
).hexdigest()[:12]


def _excerpt(text: str, keywords: list[str], window: int = 1300, max_total: int = 32000) -> str:
    low = text.lower()
    hits: list[int] = []
    for kw in keywords:
        start = 0
        while True:
            i = low.find(kw, start)
            if i == -1:
                break
            hits.append(i)
            start = i + len(kw)
    if not hits:
        return ""
    hits.sort()
    spans: list[list[int]] = []
    for i in hits:
        s = max(0, i - window)
        e = min(len(text), i + window)
        if spans and s <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], e)
        else:
            spans.append([s, e])
    out: list[str] = []
    total = 0
    for s, e in spans:
        chunk = text[s:e].strip()
        if not chunk:
            continue
        out.append(chunk)
        total += len(chunk)
        if total > max_total:
            break
    return "\n\n---\n\n".join(out)


def build_source_pack(ticker: str, fy_end: str, tenk_text: str, earnings_text: str) -> str:
    parts = [f"TICKER: {ticker}\nFISCAL YEAR END: {fy_end}\n"]
    if earnings_text:
        parts.append(
            "=== 8-K EXHIBIT 99.1 (company non-GAAP reconciliation) ===\n"
            + earnings_text[:40000]
        )
    else:
        parts.append("=== 8-K EXHIBIT 99.1 ===\n(not available)")
    tenk_excerpts = _excerpt(tenk_text or "", KEYWORDS)
    parts.append("\n=== 10-K EXCERPTS (income statement / MD&A / footnotes) ===\n" + tenk_excerpts)
    return "\n\n".join(parts)


def _cache_path(ticker: str, fy_end: str) -> Path:
    return CACHE_DIR / f"llm_{ticker}_{fy_end}.json"


def extract(ticker: str, fy_end: str, tenk_text: str, earnings_text: str) -> ExtractionResult:
    """Run (or load from cache) the LLM extraction for one company x fiscal year."""
    path = _cache_path(ticker, fy_end)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("_cache_version") == _CACHE_VERSION:
                return _from_dict(data)
        except (json.JSONDecodeError, OSError):
            pass  # corrupt or stale cache -> re-extract

    source_pack = build_source_pack(ticker, fy_end, tenk_text, earnings_text)
    user = (
        "Extract the company's reported adjusted EBITDA and all non-recurring adjustment "
        f"items from the following source material for fiscal year end {fy_end}.\n\n"
        + source_pack
    )
    data = extract_json(_SYSTEM, user, _SCHEMA)
    data["_cache_version"] = _CACHE_VERSION
    path.write_text(json.dumps(data), encoding="utf-8")
    return _from_dict(data)


def _to_float_or_none(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _from_dict(data: dict) -> ExtractionResult:
    rep = data.get("company_reported_adjusted_ebitda") or {}
    reported = ReportedAdjustedEbitda(
        amount=_to_float_or_none(rep.get("amount")),
        source_quote=rep.get("source_quote", ""),
        source_doc=rep.get("source_doc", ""),
    )
    adjustments: list[Adjustment] = []
    for item in data.get("adjustments", []):
        try:
            category = item["category"]
            sign = item["sign"]
            source_document = item.get("source_document", "")
            # Enforce the schema enums at runtime — an out-of-enum value must not slip through.
            if category not in CATEGORIES or sign not in ("add_back", "subtract"):
                continue
            if source_document not in ("10-K", "8-K_99.1"):
                continue
            adjustments.append(
                Adjustment(
                    category=category,
                    amount=float(item["amount"]),
                    sign=sign,
                    fiscal_year=0,  # overwritten by pipeline
                    fy_end="",  # overwritten by pipeline
                    source_quote=item.get("source_quote", ""),
                    source_document=source_document,
                    source_section=item.get("source_section", ""),
                    is_recurring=bool(item.get("is_recurring", False)),
                    confidence=float(item.get("confidence", 0.0) or 0.0),
                    rationale=item.get("rationale", ""),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return ExtractionResult(reported_adjusted_ebitda=reported, adjustments=adjustments)
