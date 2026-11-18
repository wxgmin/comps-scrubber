from comps.models import Financials
from comps.valuation import _as_price, compute_row, enterprise_value, market_cap


def _fin(**kw):
    base = dict(
        ticker="MSFT", name="Microsoft", cik="789019", fy_end="2025-06-30",
        fiscal_year=2025, revenue=100e9, operating_income=40e9, d_and_a=20e9,
        net_income=30e9, total_debt=50e9, cash=20e9, shares_outstanding=7.4e9,
    )
    base.update(kw)
    return Financials(**base)


def test_reported_ebitda():
    assert _fin().reported_ebitda == 60e9


def test_market_cap():
    assert market_cap(100.0, 7.4e9) == 740e9


def test_enterprise_value():
    assert enterprise_value(740e9, 50e9, 20e9) == 770e9


def test_compute_row_multiples():
    fin = _fin()
    row = compute_row(fin, 65e9, 100.0, 7.4e9)
    assert row.market_cap == 740e9
    assert row.enterprise_value == 770e9
    assert abs(row.ev_revenue - 7.7) < 1e-9
    assert abs(row.ev_ebitda_reported - 770e9 / 60e9) < 1e-9
    assert abs(row.ev_ebitda_adjusted - 770e9 / 65e9) < 1e-9
    assert abs(row.pe - 740e9 / 30e9) < 1e-9


def test_as_price_rejects_nan_inf():
    assert _as_price(float("nan")) is None
    assert _as_price(float("inf")) is None
    assert _as_price(-1.0) is None
    assert _as_price(100.0) == 100.0


def test_compute_row_negative_ebitda_is_none():
    fin = _fin(operating_income=-10e9, d_and_a=1e9)  # reported EBITDA = -9e9
    row = compute_row(fin, -8e9, 100.0, 7.4e9)
    assert row.ev_ebitda_reported is None
    assert row.ev_ebitda_adjusted is None
    assert row.ev_revenue is not None  # revenue stays positive
