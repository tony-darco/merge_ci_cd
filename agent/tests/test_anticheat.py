import difflib

from agent.guards.anticheat import check_diff

_OLD_TEST_FILE = """import pytest

def test_ten_percent_discount():
    assert apply_percentage_discount(100.0, 10) == 90.0

def test_zero_percent_discount():
    assert apply_percentage_discount(50.0, 0) == 50.0
"""


def _mkdiff(path: str, old: str, new: str) -> str:
    return "".join(difflib.unified_diff(
        old.splitlines(keepends=True), new.splitlines(keepends=True),
        fromfile=f"a/{path}", tofile=f"b/{path}",
    ))


def test_rejects_deleted_failing_test():
    new = "import pytest\n\ndef test_zero_percent_discount():\n    assert apply_percentage_discount(50.0, 0) == 50.0\n"
    diff = _mkdiff("tests/test_discounts.py", _OLD_TEST_FILE, new)
    result = check_diff(diff, failing_test_names=["test_ten_percent_discount"])
    assert result.rejected is True
    assert any("test_ten_percent_discount" in r for r in result.reject_reasons)


def test_rejects_added_skip_decorator():
    new = _OLD_TEST_FILE.replace(
        "def test_ten_percent_discount():",
        '@pytest.mark.skip(reason="flaky")\ndef test_ten_percent_discount():',
    )
    diff = _mkdiff("tests/test_discounts.py", _OLD_TEST_FILE, new)
    result = check_diff(diff)
    assert result.rejected is True
    assert any("skip" in r for r in result.reject_reasons)


def test_rejects_added_xfail_decorator():
    new = _OLD_TEST_FILE.replace(
        "def test_ten_percent_discount():",
        '@pytest.mark.xfail\ndef test_ten_percent_discount():',
    )
    diff = _mkdiff("tests/test_discounts.py", _OLD_TEST_FILE, new)
    result = check_diff(diff)
    assert result.rejected is True


def test_rejects_net_test_count_decrease_even_without_named_failing_test():
    new = "import pytest\n\ndef test_zero_percent_discount():\n    assert apply_percentage_discount(50.0, 0) == 50.0\n"
    diff = _mkdiff("tests/test_discounts.py", _OLD_TEST_FILE, new)
    result = check_diff(diff)  # no failing_test_names given
    assert result.rejected is True
    assert any("count decreases" in r for r in result.reject_reasons)


def test_assertion_change_flagged_for_review_not_rejected():
    new = _OLD_TEST_FILE.replace("== 90.0", "== 0.9")
    diff = _mkdiff("tests/test_discounts.py", _OLD_TEST_FILE, new)
    result = check_diff(diff)
    assert result.rejected is False
    assert result.requires_human_review is True
    assert any("assert" in r for r in result.review_reasons)


def test_clean_diff_passes_with_no_flags():
    old_src = "def apply_percentage_discount(amount, pct):\n    return amount * (1 - pct / 100) / 100\n"
    new_src = "def apply_percentage_discount(amount, pct):\n    return amount * (1 - pct / 100)\n"
    diff = _mkdiff("src/sample_app/discounts.py", old_src, new_src)
    result = check_diff(diff)
    assert result.rejected is False
    assert result.requires_human_review is False
    assert result.reject_reasons == []
    assert result.review_reasons == []


def test_ignores_non_test_files():
    old_src = "def f():\n    return 1\n"
    new_src = "def f():\n    return 2\n"
    diff = _mkdiff("src/sample_app/other.py", old_src, new_src)
    result = check_diff(diff)
    assert result.rejected is False
    assert result.requires_human_review is False
