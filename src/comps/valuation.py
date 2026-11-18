from __future__ import annotations

import math
from typing import Optional

from .models import CompsRow, Financials


def _as_price(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) and f > 0 else None


def get_price(ticker: str) -> Optional[float]:
    import yfinance as yf

    try:
        t = yf.Ticker(ticker)
    except Exception:
        return None
    try:
        p = _as_price(t.fast_info.get("last_price"))
        if p is not None:
            return p
    except Exception:
        pass
    try:
        h = t.history(period="5d")
        if not h.empty:
            return _as_price(h["Close"].iloc[-1])
    except Exception:
        pass
    return None


def get_shares_outstanding(ticker: str) -> Optional[float]:
    """Current shares outstanding from yfinance (fallback when XBRL has none)."""
    import yfinance as yf

    try:
        t = yf.Ticker(ticker)
    except Exception:
        return None
    try:
        info = t.info
        shares = info.get("sharesOutstanding")
        return _as_price(shares)  # same finite + positive guard
    except Exception:
        return None


def market_cap(price: Optional[float], shares: Optional[float]) -> Optional[float]:
    if price is None or shares is None or shares <= 0:
        return None
    return price * shares


def enterprise_value(mcap: Optional[float], debt: Optional[float], cash: Optional[float]) -> Optional[float]:
    if mcap is None or debt is None or cash is None:
        return None
    return mcap + debt - cash


def _ratio(numer: Optional[float], denom: Optional[float]) -> Optional[float]:
    """A valuation multiple only makes sense when both sides are positive."""
    if numer is None or denom is None or numer <= 0 or denom <= 0:
        return None
    return numer / denom


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

    row.ev_revenue = _ratio(ev, fin.revenue)
    row.ev_ebitda_reported = _ratio(ev, fin.reported_ebitda)
    row.ev_ebitda_adjusted = _ratio(ev, adjusted_ebitda)
    row.pe = _ratio(mcap, fin.net_income)
    return row
