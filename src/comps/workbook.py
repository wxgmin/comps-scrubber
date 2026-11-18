from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .models import Adjustment, CompsRow, Flag

HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
HEADER_FONT = Font(bold=True, color="FFFFFF")
LINK_FONT = Font(color="0563C1", underline="single")
TITLE_FONT = Font(bold=True, size=12)

_M = 1_000_000.0


def _num(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _write_header(ws, headers: list[str], row: int = 1) -> None:
    for c, h in enumerate(headers, 1):
        cell = ws.cell(row=row, column=c, value=h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _set_widths(ws, widths: dict[int, int]) -> None:
    for col, w in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = w


def _write_comps(ws, rows: list[CompsRow]) -> None:
    headers = [
        "Ticker", "Company", "FY", "FY End", "Price",
        "Mkt Cap ($M)", "Revenue ($M)", "Reported EBITDA ($M)", "Adjusted EBITDA ($M)",
        "Net Income ($M)", "Total Debt ($M)", "Cash ($M)", "EV ($M)",
        "EV/Revenue", "EV/EBITDA (Rpt)", "EV/EBITDA (Adj)", "P/E",
    ]
    _write_header(ws, headers)
    r = 2
    for row in rows:
        vals = [
            row.ticker, row.name, row.fiscal_year, row.fy_end,
            row.price,
            _num(row.market_cap) and row.market_cap / _M,
            _num(row.revenue) and row.revenue / _M,
            _num(row.reported_ebitda) and row.reported_ebitda / _M,
            _num(row.adjusted_ebitda) and row.adjusted_ebitda / _M,
            _num(row.net_income) and row.net_income / _M,
            _num(row.total_debt) and row.total_debt / _M,
            _num(row.cash) and row.cash / _M,
            _num(row.enterprise_value) and row.enterprise_value / _M,
            row.ev_revenue, row.ev_ebitda_reported, row.ev_ebitda_adjusted, row.pe,
        ]
        for c, v in enumerate(vals, 1):
            cell = ws.cell(row=r, column=c, value=v)
            if c in (5,):
                cell.number_format = "#,##0.00"
            elif c in (6, 7, 8, 9, 10, 11, 12, 13):
                cell.number_format = "#,##0.0"
            elif c in (14, 15, 16, 17):
                cell.number_format = "0.0x" if c in (14, 15, 16) else "0.0"
        r += 1

    # mean / median rows for the multiple columns
    multi_cols = (14, 15, 16, 17)
    for label, fn in (("Mean", _mean), ("Median", _median)):
        ws.cell(row=r, column=2, value=label).font = Font(bold=True)
        for c in multi_cols:
            col_vals = [getattr(row, _attr(c)) for row in rows]
            ws.cell(row=r, column=c, value=fn(col_vals)).number_format = (
                "0.0x" if c in (14, 15, 16) else "0.0"
            )
        r += 1
    _set_widths(ws, {1: 8, 2: 22, 3: 6, 4: 12, 5: 10, 6: 13, 7: 13, 8: 15, 9: 15,
                     10: 13, 11: 13, 12: 13, 13: 13, 14: 11, 15: 13, 16: 13, 17: 8})
    ws.freeze_panes = "A2"


def _attr(c: int) -> str:
    return {
        14: "ev_revenue",
        15: "ev_ebitda_reported",
        16: "ev_ebitda_adjusted",
        17: "pe",
    }[c]


def _mean(vals: list[Optional[float]]) -> Optional[float]:
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def _median(vals: list[Optional[float]]) -> Optional[float]:
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None
    n = len(vals)
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2


def _write_bridge(ws, ticker: str, entries: list[dict]) -> None:
    ws.cell(row=1, column=1, value=f"{ticker} — Reported → Adjusted EBITDA bridge").font = TITLE_FONT
    headers = ["Category", "Sign", "Signed Amount ($)", "Source Quote", "Section", "Source"]
    r = 3
    for entry in entries:
        ws.cell(row=r, column=1, value=f"FY{entry.get('fiscal_year')} (ended {entry.get('fy_end')})").font = Font(bold=True)
        r += 1
        ws.cell(row=r, column=1, value="Reported EBITDA (OpInc + D&A)")
        ws.cell(row=r, column=3, value=entry.get("reported_ebitda")).number_format = "#,##0"
        r += 1
        _write_header(ws, headers, row=r)
        r += 1
        for adj in entry.get("adjustments", []):
            # Route the hyperlink by the actual source document, and only show "open"
            # when a link truly exists (never a dead, clickable-looking cell).
            if adj.source_document == "10-K":
                url = entry.get("tenk_url")
            elif adj.source_document == "8-K_99.1":
                url = entry.get("earnings_url")
            else:
                url = ""
            ws.cell(row=r, column=1, value=adj.category)
            ws.cell(row=r, column=2, value=adj.sign)
            ws.cell(row=r, column=3, value=adj.signed_amount).number_format = "#,##0"
            ws.cell(row=r, column=4, value=adj.source_quote)
            ws.cell(row=r, column=5, value=adj.source_section)
            link = ws.cell(row=r, column=6, value="")
            if url:
                link.value = "open"
                link.hyperlink = url
                link.font = LINK_FONT
            r += 1
        ws.cell(row=r, column=1, value="Adjusted EBITDA (tool)").font = Font(bold=True)
        ws.cell(row=r, column=3, value=entry.get("adjusted_ebitda")).number_format = "#,##0"
        ws.cell(row=r, column=3).font = Font(bold=True)
        r += 1
        ws.cell(row=r, column=1, value="Company-reported adjusted EBITDA (reference)")
        ws.cell(row=r, column=3, value=entry.get("company_reported_adj_ebitda")).number_format = "#,##0"
        r += 2
    _set_widths(ws, {1: 34, 2: 10, 3: 18, 4: 90, 5: 22, 6: 10})
    ws.freeze_panes = "A3"


def _safe_sheet_name(ticker: str, used: set[str]) -> str:
    """Sanitize a ticker into a valid, unique Excel sheet title (<=31 chars)."""
    base = re.sub(r"[\\/*?:\[\]]", "-", ticker).strip() or "TICKER"
    name = ("Bridge - " + base)[:31]
    suffix = 2
    while name in used:
        name = f"{('Bridge - ' + base)[:28]}~{suffix}"
        suffix += 1
    used.add(name)
    return name


def _write_flags(ws, flags: list[Flag]) -> None:
    _write_header(ws, ["Ticker", "FY End", "Category", "Reason", "Detail"])
    r = 2
    for f in flags:
        ws.cell(row=r, column=1, value=f.ticker)
        ws.cell(row=r, column=2, value=f.fy_end)
        ws.cell(row=r, column=3, value=f.category)
        ws.cell(row=r, column=4, value=f.reason)
        ws.cell(row=r, column=5, value=f.detail)
        r += 1
    _set_widths(ws, {1: 8, 2: 12, 3: 20, 4: 20, 5: 100})


def write_workbook(
    comps_rows: list[CompsRow],
    bridges: dict[str, list[dict]],
    flags: list[Flag],
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    wb.remove(wb.active)

    comps = wb.create_sheet("Comps")
    _write_comps(comps, comps_rows)

    used: set[str] = {"Comps", "Flags"}
    for ticker, entries in bridges.items():
        ws = wb.create_sheet(_safe_sheet_name(ticker, used))
        _write_bridge(ws, ticker, entries)

    flags_ws = wb.create_sheet("Flags")
    _write_flags(flags_ws, flags)

    wb.save(output_path)
