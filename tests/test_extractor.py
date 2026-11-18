from comps.extractor import _from_dict


def _item(**kw):
    base = {
        "category": "Restructuring", "amount": 1_000_000, "sign": "add_back",
        "source_quote": "Restructuring charges of $1.0 million.",
        "source_document": "10-K", "source_section": "MD&A",
        "is_recurring": False, "confidence": 1.0, "rationale": "",
    }
    base.update(kw)
    return base


def _data(items):
    return {
        "company_reported_adjusted_ebitda": {
            "amount": 5_000_000, "source_quote": "Adjusted EBITDA of $5.0 million.",
            "source_doc": "8-K_99.1",
        },
        "adjustments": items,
    }


def test_from_dict_invalid_category_skipped():
    result = _from_dict(_data([_item(category="Bogus")]))
    assert result.adjustments == []


def test_from_dict_invalid_sign_skipped():
    result = _from_dict(_data([_item(sign="flip")]))
    assert result.adjustments == []


def test_from_dict_invalid_source_document_skipped():
    result = _from_dict(_data([_item(source_document="10-Q")]))
    assert result.adjustments == []


def test_from_dict_valid_item_kept():
    result = _from_dict(_data([_item()]))
    assert len(result.adjustments) == 1
    assert result.adjustments[0].amount == 1_000_000


def test_from_dict_reported_amount_coerced():
    result = _from_dict(_data([]))
    assert result.reported_adjusted_ebitda.amount == 5_000_000
