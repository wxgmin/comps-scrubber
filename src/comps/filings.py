from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from edgar import Company, set_identity

from .config import CACHE_DIR, get_sec_user_agent

# SEC requires every request to identify itself with a name + email.
set_identity(get_sec_user_agent())


def _cik_str(cik) -> str:
    return str(int(cik))


def sec_archive_url(cik, accession_no: str, document: str) -> str:
    """SEC archive URL for a specific document in a filing."""
    return (
        f"https://www.sec.gov/Archives/edgar/data/{_cik_str(cik)}/"
        f"{accession_no.replace('-', '')}/{document}"
    )


@dataclass
class FilingInfo:
    ticker: str
    name: str
    cik: str
    form: str
    filing_date: str
    period_of_report: str
    accession_no: str
    primary_document: str
    url: str
    _filing: object = None  # edgartools Filing reference for text retrieval

    @classmethod
    def from_filing(cls, ticker: str, name: str, filing) -> "FilingInfo":
        cik = _cik_str(filing.cik)
        acc = filing.accession_no
        primary = getattr(filing, "primary_document", "") or ""
        return cls(
            ticker=ticker,
            name=name,
            cik=cik,
            form=filing.form,
            filing_date=str(filing.filing_date or ""),
            period_of_report=str(filing.period_of_report or ""),
            accession_no=acc,
            primary_document=primary,
            url=sec_archive_url(cik, acc, primary) if (acc and primary) else "",
            _filing=filing,
        )


def resolve_company(ticker: str) -> tuple[str, str]:
    """Return (cik, name) for a ticker."""
    company = Company(ticker)
    return _cik_str(company.cik), company.name


def _to_date(s) -> Optional[date]:
    if not s:
        return None
    s = str(s)[:10]
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def get_recent_10ks(ticker: str, num_years: int) -> list[FilingInfo]:
    """The `num_years` most-recent distinct 10-K filings, newest period first."""
    company = Company(ticker)
    filings = company.get_filings(form="10-K")
    infos: dict[str, FilingInfo] = {}
    for f in filings:
        por = str(getattr(f, "period_of_report", "") or "")
        if por and por not in infos:  # dedupe amendments, keep first (latest) seen
            infos[por] = FilingInfo.from_filing(ticker, company.name, f)
        if len(infos) >= num_years * 2:  # safety cap on scanning
            break
    ordered = sorted(infos.values(), key=lambda i: i.period_of_report, reverse=True)
    return ordered[:num_years]


def _filing_text_cache(accession_no: str) -> Path:
    return CACHE_DIR / f"filing_{accession_no}.txt"


def get_10k_text(info: FilingInfo) -> str:
    """10-K text, cached on disk keyed by accession number."""
    path = _filing_text_cache(info.accession_no)
    if path.exists():
        return path.read_text(encoding="utf-8")
    filing = info._filing
    text = filing.text() if filing is not None else ""
    path.write_text(text or "", encoding="utf-8")
    return text or ""


def get_10k_markdown(info: FilingInfo) -> str:
    path = CACHE_DIR / f"filing_{info.accession_no}.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    filing = info._filing
    md = ""
    try:
        md = filing.markdown() or ""
    except Exception:
        md = ""
    path.write_text(md, encoding="utf-8")
    return md


def _has_non_gaap(text: str) -> bool:
    t = text.lower()
    return any(
        k in t
        for k in (
            "adjusted ebitda",
            "non-gaap",
            "non gaap",
            "reconciliation",
            "adjusted net",
            "adjusted operating",
            "adjusted eps",
            "adjusted ebit",
            "free cash flow",
            "pro forma",
        )
    )


_ANNUAL_MARKERS = ("full year", "fiscal year", "fourth quarter", "twelve months", "12 months", "annual")
_QUARTERLY_MARKERS = ("first quarter", "second quarter", "third quarter")


def _is_annual_release(text: str) -> bool:
    """True when the release reads like a full-year / Q4 annual results release."""
    t = text.lower()
    return any(m in t for m in _ANNUAL_MARKERS) and not any(m in t for m in _QUARTERLY_MARKERS)


def get_earnings_release_99_1(ticker: str, fy_end: str) -> Optional[tuple[str, str, str]]:
    """Find the 8-K / Exhibit 99.1 earnings release for a fiscal year.

    Returns (text, url, accession_no) for the annual results release, or None.
    Matches 8-K filings (ideally Item 2.02) filed within 120 days after the FYE
    whose 99.1 exhibit contains a non-GAAP / adjusted-EBITDA reconciliation.
    """
    target = _to_date(fy_end)
    if target is None:
        return None
    company = Company(ticker)
    filings = company.get_filings(form="8-K")
    matches: list[tuple[date, str, str, str]] = []
    for f in filings:
        fdate = _to_date(f.filing_date)
        if fdate is None:
            continue
        if not (target <= fdate <= target + timedelta(days=120)):
            continue
        try:
            obj = f.obj()
            items = getattr(obj, "items", None) or []
            if items and not any("2.02" in str(i) for i in items):
                continue
        except Exception:
            pass
        for ex in f.attachments.query("document_type == 'EX-99.1'").documents:
            text = ex.text() or ""
            if _has_non_gaap(text):
                matches.append((fdate, text, ex.url, f.accession_no, _is_annual_release(text)))
                break  # one 99.1 per filing
    if not matches:
        return None
    # Prefer the annual (Q4/full-year) release, then the earliest filing.
    matches.sort(key=lambda m: (not m[4], m[0]))
    _, text, url, acc, _ = matches[0]
    return text, url, acc
