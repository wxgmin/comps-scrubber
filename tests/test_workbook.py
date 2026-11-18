from pathlib import Path

from openpyxl import load_workbook

from comps.models import Adjustment, CompsRow, Flag
from comps.workbook import _safe_sheet_name, write_workbook


def test_workbook_writes(tmp_path: Path):
    rows = [
        CompsRow(
            ticker="MSFT", name="Microsoft", fy_end="2025-06-30", fiscal_year=2025,
            revenue=100e9, reported_ebitda=60e9, adjusted_ebitda=65e9, net_income=30e9,
            total_debt=50e9, cash=20e9, market_cap=740e9, enterprise_value=770e9,
            price=100.0, ev_revenue=7.7, ev_ebitda_reported=12.8, ev_ebitda_adjusted=11.8, pe=24.7,
        )
    ]
    adj = Adjustment(
        category="Restructuring", amount=5e9, sign="add_back", fiscal_year=2025,
        fy_end="2025-06-30", source_quote="Restructuring charges of $5.0 billion.",
        source_document="10-K", source_section="MD&A",
    )
    bridges = {"MSFT": [{
        "fy_end": "2025-06-30", "fiscal_year": 2025, "reported_ebitda": 60e9,
        "adjusted_ebitda": 65e9, "company_reported_adj_ebitda": 70e9,
        "tenk_url": "https://www.sec.gov/x", "earnings_url": "https://www.sec.gov/y",
        "adjustments": [adj],
    }]}
    flags = [Flag(ticker="MSFT", fy_end="2025-06-30", category="Restructuring", reason="recurring_item")]

    out = tmp_path / "test.xlsx"
    write_workbook(rows, bridges, flags, out)

    wb = load_workbook(out)
    assert "Comps" in wb.sheetnames
    assert "Bridge - MSFT" in wb.sheetnames
    assert "Flags" in wb.sheetnames


def test_safe_sheet_name_sanitizes():
    used = set()
    assert _safe_sheet_name("BRK/B", used) == "Bridge - BRK-B"


def test_safe_sheet_name_truncates():
    used = set()
    name = _safe_sheet_name("A" * 40, used)
    assert len(name) <= 31


def test_safe_sheet_name_deduplicates():
    used = set()
    a = _safe_sheet_name("MSFT", used)
    b = _safe_sheet_name("MSFT", used)
    assert a != b
