"""Flaky tests (spec §7.1): the same commit passes on retry, and a "fix" for
a flake is always wrong. Re-run once before diagnosing; if the retry passes,
stop -- it was a flake. If it reproduces, treat it as a real failure and
diagnose. M1 has no live cluster to actually retry against (fixtures-before-
cluster, DECISIONS.md #13), so the retry outcome is a boolean the orchestrator
(M4+) supplies from a real re-submission; here it's simulated in tests.
"""

from agent.llm.schema import TriageResult


def should_retry_before_diagnosis(triage_result: TriageResult) -> bool:
    return triage_result.category == "FLAKY"


def should_proceed_to_diagnosis_after_retry(retry_reproduced: bool) -> bool:
    return retry_reproduced
