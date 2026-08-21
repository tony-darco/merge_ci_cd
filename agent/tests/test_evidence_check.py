from agent.guards.evidence_check import has_sufficient_evidence


def test_empty_string_is_insufficient():
    assert has_sufficient_evidence("") is False


def test_whitespace_only_is_insufficient():
    assert has_sufficient_evidence("   \n\t  ") is False


def test_short_string_is_insufficient():
    assert has_sufficient_evidence("oops") is False


def test_real_log_content_is_sufficient():
    assert has_sufficient_evidence("FAILED tests/test_discounts.py::test_ten_percent_discount - assert 0.9 == 90.0") is True
