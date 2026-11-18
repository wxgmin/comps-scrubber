from comps.verifier import amount_in_quote, quote_matches, foot_bridge, verify_adjustment
from comps.models import Adjustment


class _FakeSEC:
    def __init__(self, val):
        self.val = val

    def xbrl_value(self, cf, tag, fy_end):
        return self.val


def test_quote_matches_exact():
    assert quote_matches("Restructuring charges of $120 million.", "We recorded Restructuring charges of $120 million.")


def test_quote_matches_whitespace_case():
    assert quote_matches("  Restructuring\ncharges  ", "restructuring charges")


def test_quote_matches_punctuation_fallback():
    assert quote_matches("Restructuring charges: $120 million.", "We recorded restructuring charges, $120 million, in Q4.")


def test_quote_no_match():
    assert not quote_matches("this sentence does not exist anywhere", "some other text")


def test_amount_in_quote_million():
    assert amount_in_quote(120_000_000, "restructuring charges of $120 million")


def test_amount_in_quote_billion():
    assert amount_in_quote(1_200_000_000, "a $1.2 billion impairment charge")


def test_amount_in_quote_thousands_table_header():
    # quote omits the "in thousands" header that lives elsewhere
    assert amount_in_quote(18_639_000, "Restructuring charges 18,639")


def test_amount_in_quote_absent():
    assert not amount_in_quote(50_000_000, "restructuring charges of $120 million")


def _adj(cat, amount, sign="add_back"):
    return Adjustment(category=cat, amount=amount, sign=sign, fiscal_year=2025, fy_end="2025-06-30", source_quote="", source_document="10-K")


def test_foot_bridge():
    adj = [_adj("Restructuring", 120_000_000), _adj("Asset_Sale", 50_000_000, sign="subtract")]
    assert foot_bridge(1_000_000_000, adj) == 1_070_000_000


def test_foot_bridge_none():
    assert foot_bridge(None, [_adj("Restructuring", 1)]) is None


def test_amount_in_quote_rejects_billion_from_million_quote():
    # 50B must not be recoverable from "$50 million" (old code allowed it via x1e3).
    assert not amount_in_quote(50_000_000_000, "$50 million")


def test_amount_in_quote_rejects_billion_from_bare_number():
    # x1e9 is gone: a bare "50" cannot validate $50B.
    assert not amount_in_quote(50_000_000_000, "restructuring charges of 50")


def test_amount_in_quote_rejects_underscaled():
    # Division fallback removed: "$120 million" cannot validate $120,000.
    assert not amount_in_quote(120_000, "$120 million")


def test_quote_matches_rejects_short_quote():
    assert not quote_matches("5", "a sentence containing 5 somewhere")


def test_verify_adjustment_rejects_xbrl_mismatch():
    sec = _FakeSEC(100_000_000)  # XBRL says $100M
    adj = _adj("Restructuring", 1_000_000)
    adj.source_quote = "Restructuring charges of $1.0 million."
    text = "We recorded restructuring charges of $1.0 million during the period."
    flag = verify_adjustment(adj, text, "", sec, {})
    assert flag is not None and flag.reason == "xbrl_mismatch"
    assert adj.verified is False


def test_verify_adjustment_sign_conflict():
    sec = _FakeSEC(50_000_000)  # a GAIN (positive) on a directional tag
    adj = _adj("Asset_Sale", 50_000_000, sign="add_back")
    adj.source_quote = "Gain on sale of assets of $50.0 million."
    text = "We recorded a gain on sale of assets of $50.0 million."
    flag = verify_adjustment(adj, text, "", sec, {})
    assert flag is None  # magnitude verified, not rejected
    assert adj.sign_conflict is True
