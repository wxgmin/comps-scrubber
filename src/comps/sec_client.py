from __future__ import annotations

import json
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import requests

from .config import CACHE_DIR, get_sec_user_agent

XBRL = "https://data.sec.gov/api/xbrl"

# us-gaap tags attempted in order for the income-statement measures we need.
REVENUE_TAGS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
]
OPERATING_INCOME_TAG = "OperatingIncomeLoss"
DA_COMBINED_TAGS = [
    "DepreciationDepletionAndAmortization",
    "DepreciationAmortizationAndAccretionNet",
]
DA_COMPONENT_TAGS = ["Depreciation", "AmortizationOfIntangibleAssets"]
NET_INCOME_TAG = "NetIncomeLoss"
CASH_TAGS = [
    "CashAndCashEquivalentsAtCarryingValue",
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
]
# `DebtLongtermAndShorttermCombinedAmount` is the canonical total-debt tag. We deliberately
# do NOT use `DebtInstrumentCarryingAmount` here: it is a per-instrument tag (one fact per
# tranche), not an aggregate.
TOTAL_DEBT_TAGS = ["DebtLongtermAndShorttermCombinedAmount"]
ST_DEBT_TAGS = ["ShortTermBorrowings"]
LEASE_TAGS = [
    "FinanceLeaseLiabilityCurrent",
    "FinanceLeaseLiabilityNoncurrent",
    "CapitalLeaseObligationsCurrent",
    "CapitalLeaseObligationsNoncurrent",
]
CONVERTIBLE_TAGS = [
    "ConvertibleDebt",
    "ConvertibleDebtNoncurrent",
    "ConvertibleDebtCurrent",
    "ConvertibleNotesPayableCurrent",
    "ConvertibleLongTermNotesPayable",
]
SHARES_TAG = "EntityCommonStockSharesOutstanding"  # dei namespace


def cik10(cik) -> str:
    return f"CIK{int(cik):010d}"


def _parse_date(s: str) -> Optional[date]:
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def annual_facts_from_10k(facts: list[dict]) -> list[dict]:
    """One full-year duration fact per period-end from 10-K / 10-K/A; latest filing wins.

    Guards against the SEC companyfacts traps: `fy` is the filing's year (ignored),
    duplicates are normal (deduped), and proxy/other filings are excluded by form.
    """
    best: dict[str, dict] = {}
    for f in facts:
        if f.get("form") not in ("10-K", "10-K/A") or "start" not in f:
            continue
        start = _parse_date(f.get("start"))
        end = _parse_date(f.get("end"))
        if start is None or end is None:
            continue
        if not (350 <= (end - start).days <= 380):
            continue
        key = f["end"]
        if key not in best or f.get("filed", "") > best[key].get("filed", ""):
            best[key] = f
    return [best[k] for k in sorted(best)]


def _nearest_instant(facts: list[dict], fy_end: str) -> Optional[dict]:
    """Pick the balance-sheet (instant) fact for a fiscal-year end.

    Instant facts have no `start`; duration (flow) facts do. Dedupe by period-end
    keeping the latest `filed` (handles 10-K/A amendments), prefer an exact date,
    then the nearest date within 7 days AFTER the FYE (never before).
    """
    target = _parse_date(fy_end)
    if target is None:
        return None
    best_by_end: dict[str, dict] = {}
    for f in facts:
        if f.get("form") not in ("10-K", "10-K/A") or "start" in f:
            continue
        end = f.get("end")
        if end and (
            end not in best_by_end
            or f.get("filed", "") > best_by_end[end].get("filed", "")
        ):
            best_by_end[end] = f
    if fy_end in best_by_end:
        return best_by_end[fy_end]
    best, best_diff = None, None
    for end, f in best_by_end.items():
        d = _parse_date(end)
        if d is None:
            continue
        diff = (d - target).days
        if 0 <= diff <= 7 and (best_diff is None or diff < best_diff):
            best, best_diff = f, diff
    return best


def _nearest_duration(facts: list[dict], fy_end: str) -> Optional[dict]:
    annual = annual_facts_from_10k(facts)
    for f in annual:
        if f["end"] == fy_end:
            return f
    target = _parse_date(fy_end)
    if target is None:
        return None
    best, best_diff = None, None
    for f in annual:
        end = _parse_date(f.get("end"))
        if end is None:
            continue
        diff = abs((end - target).days)
        if best_diff is None or diff < best_diff:
            best, best_diff = f, diff
    return best if (best_diff is not None and best_diff <= 7) else None


class SECClient:
    def __init__(self, cache_dir: Path = CACHE_DIR):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.headers = {"User-Agent": get_sec_user_agent()}

    def _cache_path(self, cik) -> Path:
        return self.cache_dir / f"companyfacts_{cik10(cik)}.json"

    def get_companyfacts(self, cik) -> dict:
        path = self._cache_path(cik)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        url = f"{XBRL}/companyfacts/{cik10(cik)}.json"
        r = requests.get(url, headers=self.headers, timeout=60)
        r.raise_for_status()
        data = r.json()
        path.write_text(json.dumps(data), encoding="utf-8")
        time.sleep(0.15)  # stay under SEC's 10 req/s limit
        return data

    # --- tag helpers ---

    def _usd_facts(self, cf: dict, tag: str) -> list[dict]:
        return cf["facts"].get("us-gaap", {}).get(tag, {}).get("units", {}).get("USD", [])

    def _shares_facts(self, cf: dict) -> list[dict]:
        return (
            cf["facts"]
            .get("dei", {})
            .get(SHARES_TAG, {})
            .get("units", {})
            .get("shares", [])
        )

    def _duration_usd(self, cf: dict, tag: str, fy_end: str) -> Optional[float]:
        f = _nearest_duration(self._usd_facts(cf, tag), fy_end)
        return f.get("val") if f else None

    def _instant_usd(self, cf: dict, tag: str, fy_end: str) -> Optional[float]:
        f = _nearest_instant(self._usd_facts(cf, tag), fy_end)
        return f.get("val") if f else None

    # --- public extractors ---

    def revenue(self, cf: dict, fy_end: str) -> Optional[float]:
        for tag in REVENUE_TAGS:
            v = self._duration_usd(cf, tag, fy_end)
            if v is not None:
                return v
        return None

    def operating_income(self, cf: dict, fy_end: str) -> Optional[float]:
        return self._duration_usd(cf, OPERATING_INCOME_TAG, fy_end)

    def depreciation_amortization(self, cf: dict, fy_end: str) -> Optional[float]:
        for tag in DA_COMBINED_TAGS:
            v = self._duration_usd(cf, tag, fy_end)
            if v is not None:
                return v
        components = [self._duration_usd(cf, tag, fy_end) for tag in DA_COMPONENT_TAGS]
        present = [v for v in components if v is not None]
        return sum(present) if present else None

    def net_income(self, cf: dict, fy_end: str) -> Optional[float]:
        return self._duration_usd(cf, NET_INCOME_TAG, fy_end)

    def cash(self, cf: dict, fy_end: str) -> Optional[float]:
        for tag in CASH_TAGS:
            v = self._instant_usd(cf, tag, fy_end)
            if v is not None:
                return v
        return None

    def total_debt(self, cf: dict, fy_end: str) -> Optional[float]:
        """Total interest-bearing debt (LT debt incl. current portion + short-term borrowings
        + finance leases + convertible notes, when the filer reports them separately).

        Precedence avoids double-counting: the canonical combined tag wins; otherwise the
        split LT-debt tags are summed and convertible notes are added only when the filer
        reports no traditional LT-debt tag at all (convertibles are otherwise usually folded
        into LongTermDebt*).
        """
        for tag in TOTAL_DEBT_TAGS:
            v = self._instant_usd(cf, tag, fy_end)
            if v is not None:
                return v

        lt = self._instant_usd(cf, "LongTermDebt", fy_end)
        if lt is None:
            n = self._instant_usd(cf, "LongTermDebtNoncurrent", fy_end)
            c = self._instant_usd(cf, "LongTermDebtCurrent", fy_end)
            if n is not None or c is not None:
                lt = (n or 0.0) + (c or 0.0)

        total = lt if lt is not None else 0.0
        found = lt is not None

        st = self._instant_usd(cf, "ShortTermBorrowings", fy_end)
        if st is not None:
            total += st
            found = True

        for tag in LEASE_TAGS:
            v = self._instant_usd(cf, tag, fy_end)
            if v is not None:
                total += v
                found = True

        if lt is None:  # convertibles are the primary debt when no LT-debt tag exists
            for tag in CONVERTIBLE_TAGS:
                v = self._instant_usd(cf, tag, fy_end)
                if v is not None:
                    total += v
                    found = True

        return total if found else None

    def shares_outstanding(self, cf: dict, fy_end: str) -> Optional[float]:
        # Cover-page "shares outstanding" is dated shortly AFTER the fiscal-year end,
        # so match 10-K facts within a +90-day window instead of an exact date.
        target = _parse_date(fy_end)
        if target is None:
            return None
        facts = [
            f for f in self._shares_facts(cf) if f.get("form") in ("10-K", "10-K/A")
        ]
        # Fallback: some filers report period-end shares as us-gaap CommonStockSharesOutstanding.
        facts += [
            f
            for f in cf["facts"].get("us-gaap", {})
            .get("CommonStockSharesOutstanding", {})
            .get("units", {})
            .get("shares", [])
            if f.get("form") in ("10-K", "10-K/A")
        ]
        if not facts:
            return None
        window = [
            f
            for f in facts
            if (end := _parse_date(f.get("end"))) is not None
            and target <= end <= target + timedelta(days=90)
        ]
        if not window:
            return None  # no share count near this FYE; don't guess
        best = min(window, key=lambda f: (_parse_date(f.get("end")) - target).days)
        return best.get("val") if best else None

    def xbrl_value(self, cf: dict, tag: str, fy_end: str) -> Optional[float]:
        """Cross-check helper: look up an arbitrary us-gaap tag for a FY end.

        Tries duration first, then instant, since some tags are reported either way.
        """
        v = self._duration_usd(cf, tag, fy_end)
        if v is not None:
            return v
        return self._instant_usd(cf, tag, fy_end)
