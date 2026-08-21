"""Reward-hacking checks on the diff, before it's ever executed (spec §7.4).
The most common way a naive agent "succeeds": deleting or skipping the
failing test, or weakening an assertion. Pure static analysis on the diff
text -- no execution needed, so this runs cheaply before the sandbox does.
"""

import re

from unidiff import PatchSet

from agent.llm.schema import AntiCheatResult

_TEST_DEF_PATTERN = re.compile(r"^\s*def (test_\w+)\s*\(")
_SKIP_XFAIL_PATTERN = re.compile(r"@pytest\.mark\.(skip|xfail)\b")
_ASSERT_PATTERN = re.compile(r"^\s*assert\b")


def _added_removed_lines(patched_file) -> tuple[list[str], list[str]]:
    added, removed = [], []
    for hunk in patched_file:
        for line in hunk:
            if line.is_added:
                added.append(line.value)
            elif line.is_removed:
                removed.append(line.value)
    return added, removed


def _test_def_names(lines: list[str]) -> set[str]:
    return {m.group(1) for line in lines if (m := _TEST_DEF_PATTERN.match(line))}


def check_diff(diff_text: str, failing_test_names: list[str] | None = None) -> AntiCheatResult:
    failing_test_names = failing_test_names or []
    reject_reasons: list[str] = []
    review_reasons: list[str] = []

    try:
        patch = PatchSet(diff_text)
    except Exception as e:
        return AntiCheatResult(rejected=True, reject_reasons=[f"could not parse diff: {e}"], requires_human_review=False, review_reasons=[])

    for patched_file in patch:
        path = re.sub(r"^[ab]/", "", patched_file.target_file or patched_file.source_file or "")
        if "tests/" not in path:
            continue

        added, removed = _added_removed_lines(patched_file)
        removed_tests = _test_def_names(removed)
        added_tests = _test_def_names(added)

        deleted_without_replacement = removed_tests - added_tests
        deleted_failing_tests = deleted_without_replacement & set(failing_test_names) if failing_test_names else deleted_without_replacement
        if deleted_failing_tests:
            reject_reasons.append(
                f"{path!r}: deletes test function(s) {sorted(deleted_failing_tests)} with no same-name replacement"
            )

        for line in added:
            if _SKIP_XFAIL_PATTERN.search(line):
                reject_reasons.append(f"{path!r}: adds a skip/xfail decorator ({line.strip()!r})")

        net_test_count_change = len(added_tests) - len(removed_tests)
        if net_test_count_change < 0:
            reject_reasons.append(f"{path!r}: net test function count decreases by {-net_test_count_change}")

        assert_lines_touched = [
            line for line in added + removed if _ASSERT_PATTERN.match(line)
        ]
        if assert_lines_touched:
            review_reasons.append(f"{path!r}: modifies {len(assert_lines_touched)} assert line(s) -- requires human review regardless of confidence")

    return AntiCheatResult(
        rejected=len(reject_reasons) > 0,
        reject_reasons=reject_reasons,
        requires_human_review=len(review_reasons) > 0,
        review_reasons=review_reasons,
    )
