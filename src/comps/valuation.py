from __future__ import annotations

from typing import Optional

from .models import CompsRow, Financials


def get_price(ticker: str) -> Optional[float]:
    import yfinance as yf

    t = yf.Ticker(ticker)
    try:
        p = t.fast_info.get("last_price")
        if p:
            return float(p)
    except Exception:
        pass
    try:
        h = t.history(period="5d")
        if not h.empty:
            return float(h["Close"].iloc[-1])
    except Exception:
        pass
    return None


def market_cap(price: Optional[float], shares: Optional[float]) -> Optional[float]:
    if price is None or shares is None or shares <= 0:
        return None
    return price * shares


def enterprise_value(mcap: Optional[float], debt: Optional[float], cash: Optional[float]) -> Optional[float]:
    if mcap is None or debt is None or cash is None:
        return None
    return mcap + debt - cash


def compute_row(
    fin: Financials,
    adjusted_ebitda: Optional[float],
    price: Optional[float],
    shares_for_mcap: Optional[float],
) -> CompsRow:
    row = CompsRow(
        ticker=fin.ticker,
        name=fin.name,
        fy_end=fin.fy_end,
        fiscal_year=fin.fiscal_year,
        revenue=fin.revenue,
        reported_ebitda=fin.reported_ebitda,
        adjusted_ebitda=adjusted_ebitda,
        net_income=fin.net_income,
        total_debt=fin.total_debt,
        cash=fin.cash,
        price=price,
    )
    mcap = market_cap(price, shares_for_mcap)
    row.market_cap = mcap
    ev = enterprise_value(mcap, fin.total_debt, fin.cash)
    row.enterprise_value = ev

    if ev and fin.revenue:
        row.ev_revenue = ev / fin.revenue
    if ev and fin.reported_ebitda and fin.reported_ebitda > 0:
        row.ev_ebitda_reported = ev / fin.reported_ebitda
    if ev and adjusted_ebitda and adjusted_ebitda > 0:
        row.ev_ebitda_adjusted = ev / adjusted_ebitda
    if mcap and fin.net_income and fin.net_income > 0:
        row.pe = mcap / fin.net_income
    return row


def _mean(vals: list[float]) -> Optional[float]:
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def _median(vals: list[float]) -> Optional[float]:
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None
    n = len(vals)
    mid = n // 2
    return vals[mid] if n % 2 else (vals[mid - 1] + vals[mid]) / 2
