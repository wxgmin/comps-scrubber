from comps.config import CategoryPolicy, Policy
from comps.models import Adjustment, Flag
from comps.policy import apply_policy


def _adj(category, sign="add_back", **kw):
    base = dict(
        category=category, amount=50_000_000, sign=sign, fiscal_year=2025,
        fy_end="2025-06-30", source_quote="", source_document="10-K",
    )
    base.update(kw)
    return Adjustment(**base)


def _policy(**categories):
    cats = {name: CategoryPolicy(treatment) for name, treatment in categories.items()}
    return Policy(categories=cats)


def test_disabled_category_dropped():
    p = _policy(Restructuring="add_back", StockBasedCompensation="add_back")
    p.categories["StockBasedCompensation"].enabled = False
    included, flags = apply_policy(
        [_adj("Restructuring"), _adj("StockBasedCompensation")], p, "MSFT", "2025-06-30"
    )
    assert [a.category for a in included] == ["Restructuring"]
    assert flags == []


def test_unknown_category_fails_closed():
    p = _policy(Restructuring="add_back")
    included, flags = apply_policy([_adj("Bogus")], p, "MSFT", "2025-06-30")
    assert included == []
    assert any(f.reason == "unknown_category" for f in flags)


def test_auto_sign_correction_on_conflict():
    p = _policy(Asset_Sale="auto")
    adj = _adj("Asset_Sale", sign="add_back", sign_conflict=True, xbrl_match=50_000_000)
    included, flags = apply_policy([adj], p, "MSFT", "2025-06-30")
    assert included[0].sign == "subtract"  # gain corrected away from add_back
    assert any(f.reason == "sign_conflict" for f in flags)


def test_forced_add_back_overrides():
    p = _policy(Restructuring="add_back")
    adj = _adj("Restructuring", sign="subtract")  # LLM guessed wrong
    included, _ = apply_policy([adj], p, "MSFT", "2025-06-30")
    assert included[0].sign == "add_back"


def test_recurring_flag():
    p = _policy(Restructuring="add_back")
    adj = _adj("Restructuring", is_recurring=True)
    included, flags = apply_policy([adj], p, "MSFT", "2025-06-30")
    assert len(included) == 1
    assert any(f.reason == "recurring_item" for f in flags)
