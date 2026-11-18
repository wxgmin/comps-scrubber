from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

CATEGORIES = [
    "Restructuring",
    "Impairment",
    "Litigation",
    "M&A_Transaction",
    "Asset_Sale",
    "StockBasedCompensation",
    "Other_NonRecurring",
]


@dataclass
class Financials:
    ticker: str
    name: str
    cik: str
    fy_end: str
    fiscal_year: int
    revenue: Optional[float] = None
    operating_income: Optional[float] = None
    d_and_a: Optional[float] = None
    net_income: Optional[float] = None
    total_debt: Optional[float] = None
    cash: Optional[float] = None
    shares_outstanding: Optional[float] = None
    tenk_accession: Optional[str] = None
    tenk_primary_doc: Optional[str] = None

    @property
    def reported_ebitda(self) -> Optional[float]:
        if self.operating_income is None or self.d_and_a is None:
            return None
        return self.operating_income + self.d_and_a

    @property
    def period_label(self) -> str:
        return f"FY{self.fiscal_year}"


@dataclass
class Adjustment:
    category: str
    amount: float
    sign: str  # "add_back" | "subtract"
    fiscal_year: int
    fy_end: str
    source_quote: str
    source_document: str
    source_section: str = ""
    is_recurring: bool = False
    confidence: float = 0.0
    rationale: str = ""
    # filled in by the verifier
    verified: bool = False
    verification_status: str = ""
    xbrl_match: Optional[float] = None

    @property
    def signed_amount(self) -> float:
        return self.amount if self.sign == "add_back" else -self.amount


@dataclass
class ReportedAdjustedEbitda:
    amount: Optional[float] = None
    source_quote: str = ""
    source_doc: str = ""


@dataclass
class ExtractionResult:
    reported_adjusted_ebitda: ReportedAdjustedEbitda = field(
        default_factory=lambda: ReportedAdjustedEbitda(None)
    )
    adjustments: list[Adjustment] = field(default_factory=list)


@dataclass
class Flag:
    ticker: str
    fy_end: str
    category: str
    reason: str
    detail: str = ""


@dataclass
class CompsRow:
    ticker: str
    name: str
    fy_end: str
    fiscal_year: int
    revenue: Optional[float] = None
    reported_ebitda: Optional[float] = None
    adjusted_ebitda: Optional[float] = None
    net_income: Optional[float] = None
    total_debt: Optional[float] = None
    cash: Optional[float] = None
    market_cap: Optional[float] = None
    enterprise_value: Optional[float] = None
    price: Optional[float] = None
    ev_revenue: Optional[float] = None
    ev_ebitda_reported: Optional[float] = None
    ev_ebitda_adjusted: Optional[float] = None
    pe: Optional[float] = None
