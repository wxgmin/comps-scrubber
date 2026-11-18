from comps.verifier import amount_in_quote, quote_matches, foot_bridge
from comps.models import Adjustment


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
