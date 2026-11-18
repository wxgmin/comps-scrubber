from comps.sec_client import annual_facts_from_10k, cik10


def _fact(form, start, end, val, filed="2025-01-01"):
    return {"form": form, "start": start, "end": end, "val": val, "filed": filed}


def test_cik10_pads():
    assert cik10(320193) == "CIK0000320193"


def test_annual_facts_from_10k_filters_form():
    facts = [
        _fact("10-K", "2024-01-01", "2024-12-31", 100),
        _fact("10-Q", "2024-01-01", "2024-03-31", 999),
        _fact("DEF 14A", "2024-01-01", "2024-12-31", 999999),
    ]
    out = annual_facts_from_10k(facts)
    assert len(out) == 1
    assert out[0]["val"] == 100


def test_annual_facts_from_10k_dedupes_latest_filing():
    facts = [
        _fact("10-K", "2024-01-01", "2024-12-31", 100, filed="2025-02-20"),
        _fact("10-K", "2024-01-01", "2024-12-31", 120, filed="2026-02-20"),
    ]
    out = annual_facts_from_10k(facts)
    assert len(out) == 1
    assert out[0]["val"] == 120


def test_annual_facts_from_10k_requires_full_year():
    facts = [
        _fact("10-K", "2024-01-01", "2024-03-31", 100),  # quarter-like duration
        _fact("10-K", "2024-01-01", "2024-12-31", 200),
    ]
    out = annual_facts_from_10k(facts)
    assert [f["val"] for f in out] == [200]
