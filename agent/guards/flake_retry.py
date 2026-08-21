"""Flaky tests (spec §7.1): the same commit passes on retry, and a "fix" for
a flake is always wrong. Re-run once before diagnosing; if the retry passes,
stop -- it was a flake. If it reproduces, treat it as a real failure and
diagnose. M1 had no live cluster to actually retry against (fixtures-before-
cluster, DECISIONS.md #13), so the retry outcome was simulated in tests;
M4's orchestrator supplies a real one via retry_flaky_test_locally below --
still no cluster needed, since the flaky seed test has no package
dependency and can be re-run directly against a worktree checkout.
"""

import subprocess
import sys
from pathlib import Path

from agent.llm.schema import TriageResult


def should_retry_before_diagnosis(triage_result: TriageResult) -> bool:
    return triage_result.category == "FLAKY"


def should_proceed_to_diagnosis_after_retry(retry_reproduced: bool) -> bool:
    return retry_reproduced


def retry_flaky_test_locally(checkout_path: Path, test_node_id: str) -> bool:
    """Re-runs the specific failing test node against a local checkout --
    no cluster, no Docker. Returns True if it reproduced (failed again),
    False if it passed (a confirmed flake).
    """
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", test_node_id],
        cwd=checkout_path,
        capture_output=True,
        text=True,
    )
    return result.returncode != 0
