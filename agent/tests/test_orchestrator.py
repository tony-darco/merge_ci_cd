"""M4 exit checks. The two refusal paths (infra-failure, config-secret) are
real end-to-end runs -- they never touch the LLM, so there's nothing to
mock and no reason not to run the whole graph for real. Retry-with-feedback,
human-review-stop, and full-success confidence scoring mock the agent
functions directly (as the plan calls for) so routing logic is tested in
isolation from live Ollama/Docker. The flaky-retry test mocks only Triage
(the one LLM-dependent step) and lets retry_flaky_test_locally actually
re-run the real, nondeterministic-by-construction test against a real
worktree checkout -- whichever way that coin flip lands, the wiring on
both branches gets exercised across enough runs.
"""

import subprocess
import tempfile
from pathlib import Path

import pytest

import agent.orchestrator as orch
from agent.llm.schema import (
    AntiCheatResult,
    DiagnosisResult,
    FixResult,
    TestRunSummary,
    TriageResult,
    VerificationResult,
)
from agent.orchestrator import build_graph, run_orchestrator
from agent.tests.fixtures import load_fixture

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_APP_DIR = REPO_ROOT / "sample-app"


def _fake_diagnosis() -> DiagnosisResult:
    return DiagnosisResult(
        root_cause="mocked root cause",
        evidence=[],
        alternative_hypothesis="",
        affected_files=["src/sample_app/discounts.py"],
        category="CODE_DEFECT",
    )


def _fake_fix() -> FixResult:
    return FixResult(
        diff="--- a/src/x.py\n+++ b/src/x.py\n@@ -1 +1 @@\n-old\n+new\n",
        rationale="mocked fix",
        blast_radius="1 file, 1 line",
        lockfile_change_reason=None,
    )


def _fake_verification(passed: bool, delta: str) -> VerificationResult:
    if passed:
        return VerificationResult(
            baseline_summary=TestRunSummary(passed_tests=[], failed_tests=["test_x"]),
            patched_summary=TestRunSummary(passed_tests=["test_x"], failed_tests=[]),
            delta=delta, passed=True, regressions=[], newly_passing=["test_x"],
        )
    return VerificationResult(
        baseline_summary=TestRunSummary(passed_tests=[], failed_tests=["test_x"]),
        patched_summary=TestRunSummary(passed_tests=[], failed_tests=["test_x"]),
        delta=delta, passed=False, regressions=[], newly_passing=[],
    )


def _patch_verifier(monkeypatch, run_fn):
    """The verify node resolves a Verifier via get_verifier() (DECISIONS.md
    #27), so routing tests patch that seam rather than a module-level
    function. run_fn(checkout_path, diff_text) -> VerificationResult.
    """

    class _FakeVerifier:
        name = "fake"

        def run(self, checkout_path, diff_text):
            return run_fn(checkout_path, diff_text)

    monkeypatch.setattr(orch, "get_verifier", lambda: _FakeVerifier())


def _mock_happy_path(monkeypatch):
    """Everything green through to confidence, so a test can focus on what
    happens after -- used by the PR-gating cases below.
    """
    from agent.guards.scope import ScopeCheckResult

    monkeypatch.setattr(orch, "run_triage", lambda c, p: TriageResult(
        category="CODE_DEFECT", reasoning="mocked", evidence_summary="mocked"))
    monkeypatch.setattr(orch, "run_diagnosis", lambda c, r, p: _fake_diagnosis())
    monkeypatch.setattr(orch, "run_fix", lambda d, c, cp, p, verification_feedback=None: _fake_fix())
    monkeypatch.setattr(orch, "validate_diff", lambda d, r=None: ScopeCheckResult(rejected=False, reasons=[]))
    monkeypatch.setattr(orch, "check_diff", lambda d, failing_test_names=None: AntiCheatResult(
        rejected=False, reject_reasons=[], requires_human_review=False, review_reasons=[]))
    _patch_verifier(monkeypatch, lambda cp, d: _fake_verification(passed=True, delta="0 failed"))


def _base_state() -> dict:
    return {
        "context": load_fixture("code-defect"),
        "checkout_path": Path("/nonexistent"),  # unused -- every agent fn is mocked
        "provider": None,
        "fix_attempts": 0,
        "llm_calls": 0,
    }


def test_retry_with_feedback_then_succeeds(monkeypatch):
    fix_calls: list[str | None] = []
    verify_call_count = {"n": 0}

    def fake_run_triage(context, provider):
        return TriageResult(category="CODE_DEFECT", reasoning="mocked", evidence_summary="mocked")

    def fake_run_diagnosis(context, root_node, provider):
        return _fake_diagnosis()

    def fake_run_fix(diagnosis, context, checkout_path, provider, verification_feedback=None):
        fix_calls.append(verification_feedback)
        return _fake_fix()

    def fake_validate_diff(diff_text, lockfile_change_reason=None):
        from agent.guards.scope import ScopeCheckResult
        return ScopeCheckResult(rejected=False, reasons=[])

    def fake_check_diff(diff_text, failing_test_names=None):
        return AntiCheatResult(rejected=False, reject_reasons=[], requires_human_review=False, review_reasons=[])

    def fake_run_verification(checkout_path, diff_text):
        verify_call_count["n"] += 1
        if verify_call_count["n"] == 1:
            return _fake_verification(passed=False, delta="1 still failing")
        return _fake_verification(passed=True, delta="0 failed")

    monkeypatch.setattr(orch, "run_triage", fake_run_triage)
    monkeypatch.setattr(orch, "run_diagnosis", fake_run_diagnosis)
    monkeypatch.setattr(orch, "run_fix", fake_run_fix)
    monkeypatch.setattr(orch, "validate_diff", fake_validate_diff)
    monkeypatch.setattr(orch, "check_diff", fake_check_diff)
    _patch_verifier(monkeypatch, fake_run_verification)

    final_state = build_graph().invoke(_base_state())

    assert fix_calls == [None, "1 still failing"], "fix should run twice: first clean, then fed the failure back"
    assert verify_call_count["n"] == 2
    assert final_state["verification"].passed is True
    assert final_state["fix_attempts"] == 2
    assert "confidence" in final_state


def test_unresolved_after_max_fix_attempts(monkeypatch):
    def fake_run_triage(context, provider):
        return TriageResult(category="CODE_DEFECT", reasoning="mocked", evidence_summary="mocked")

    def fake_run_diagnosis(context, root_node, provider):
        return _fake_diagnosis()

    def fake_run_fix(diagnosis, context, checkout_path, provider, verification_feedback=None):
        return _fake_fix()

    def fake_validate_diff(diff_text, lockfile_change_reason=None):
        from agent.guards.scope import ScopeCheckResult
        return ScopeCheckResult(rejected=False, reasons=[])

    def fake_check_diff(diff_text, failing_test_names=None):
        return AntiCheatResult(rejected=False, reject_reasons=[], requires_human_review=False, review_reasons=[])

    def fake_run_verification(checkout_path, diff_text):
        return _fake_verification(passed=False, delta="still failing")

    monkeypatch.setattr(orch, "run_triage", fake_run_triage)
    monkeypatch.setattr(orch, "run_diagnosis", fake_run_diagnosis)
    monkeypatch.setattr(orch, "run_fix", fake_run_fix)
    monkeypatch.setattr(orch, "validate_diff", fake_validate_diff)
    monkeypatch.setattr(orch, "check_diff", fake_check_diff)
    _patch_verifier(monkeypatch, fake_run_verification)

    final_state = build_graph().invoke(_base_state())

    assert final_state["fix_attempts"] == orch.MAX_FIX_ATTEMPTS
    assert final_state["verification"].passed is False
    assert "confidence" not in final_state
    assert "unresolved" in orch.describe_outcome(final_state)


def test_human_review_flag_stops_before_verify(monkeypatch):
    def fake_run_triage(context, provider):
        return TriageResult(category="CODE_DEFECT", reasoning="mocked", evidence_summary="mocked")

    def fake_run_diagnosis(context, root_node, provider):
        return _fake_diagnosis()

    def fake_run_fix(diagnosis, context, checkout_path, provider, verification_feedback=None):
        return _fake_fix()

    def fake_validate_diff(diff_text, lockfile_change_reason=None):
        from agent.guards.scope import ScopeCheckResult
        return ScopeCheckResult(rejected=False, reasons=[])

    def fake_check_diff(diff_text, failing_test_names=None):
        return AntiCheatResult(
            rejected=False, reject_reasons=[],
            requires_human_review=True, review_reasons=["modifies an assert line"],
        )

    def never_called_verify(*a, **kw):
        raise AssertionError("verify must not run when anticheat flags human review")

    monkeypatch.setattr(orch, "run_triage", fake_run_triage)
    monkeypatch.setattr(orch, "run_diagnosis", fake_run_diagnosis)
    monkeypatch.setattr(orch, "run_fix", fake_run_fix)
    monkeypatch.setattr(orch, "validate_diff", fake_validate_diff)
    monkeypatch.setattr(orch, "check_diff", fake_check_diff)
    _patch_verifier(monkeypatch, never_called_verify)

    final_state = build_graph().invoke(_base_state())

    assert "verification" not in final_state
    assert final_state["anticheat_result"].requires_human_review is True
    assert "human review" in orch.describe_outcome(final_state)


def test_full_success_path_computes_high_confidence(monkeypatch):
    def fake_run_triage(context, provider):
        return TriageResult(category="CODE_DEFECT", reasoning="mocked", evidence_summary="mocked")

    def fake_run_diagnosis(context, root_node, provider):
        return _fake_diagnosis()

    def fake_run_fix(diagnosis, context, checkout_path, provider, verification_feedback=None):
        return _fake_fix()

    def fake_validate_diff(diff_text, lockfile_change_reason=None):
        from agent.guards.scope import ScopeCheckResult
        return ScopeCheckResult(rejected=False, reasons=[])

    def fake_check_diff(diff_text, failing_test_names=None):
        return AntiCheatResult(rejected=False, reject_reasons=[], requires_human_review=False, review_reasons=[])

    def fake_run_verification(checkout_path, diff_text):
        return _fake_verification(passed=True, delta="0 failed")

    monkeypatch.setattr(orch, "run_triage", fake_run_triage)
    monkeypatch.setattr(orch, "run_diagnosis", fake_run_diagnosis)
    monkeypatch.setattr(orch, "run_fix", fake_run_fix)
    monkeypatch.setattr(orch, "validate_diff", fake_validate_diff)
    monkeypatch.setattr(orch, "check_diff", fake_check_diff)
    _patch_verifier(monkeypatch, fake_run_verification)

    final_state = build_graph().invoke(_base_state())

    assert final_state["confidence"] == "HIGH"
    assert final_state["fix_attempts"] == 1
    assert "verified fix" in orch.describe_outcome(final_state)


def test_infra_failure_refuses_at_triage_without_llm():
    final_state = run_orchestrator("infra-failure")
    assert final_state["triage"].category == "INFRA_FAILURE"
    assert "diagnosis" not in final_state
    assert "fix" not in final_state


def test_config_secret_refuses_at_triage_without_llm():
    final_state = run_orchestrator("config-secret")
    assert final_state["triage"].category == "CONFIG_OR_SECRET"
    assert "diagnosis" not in final_state
    assert "fix" not in final_state


@pytest.fixture
def flaky_checkout():
    with tempfile.TemporaryDirectory(prefix="test-orch-flaky-") as scratch:
        subprocess.run(
            ["git", "-C", str(SAMPLE_APP_DIR), "worktree", "add", "--detach", scratch, "seed/flaky-test"],
            check=True, capture_output=True, text=True,
        )
        try:
            yield Path(scratch)
        finally:
            subprocess.run(
                ["git", "-C", str(SAMPLE_APP_DIR), "worktree", "remove", "--force", scratch],
                check=False, capture_output=True, text=True,
            )


def test_flaky_path_retries_against_real_checkout(monkeypatch, flaky_checkout):
    """Exercises the real retry: `retry_flaky_test_locally` actually re-runs
    the seeded test, which fails ~15% of the time by construction, so either
    branch can be taken on any given run.

    Everything downstream of the retry is mocked -- including diagnosis.
    That is not incidental: the reproduced branch continues into Diagnosis,
    and an earlier version of this test left it unmocked with provider=None,
    so the test itself failed roughly 15% of the time. A flaky test for the
    flaky-test path is a special kind of unhelpful (see LOG.md).
    """
    from agent.guards.scope import ScopeCheckResult

    monkeypatch.setattr(orch, "run_triage", lambda c, p: TriageResult(
        category="FLAKY", reasoning="mocked", evidence_summary="mocked"))
    monkeypatch.setattr(orch, "run_diagnosis", lambda c, r, p: _fake_diagnosis())
    monkeypatch.setattr(orch, "run_fix", lambda d, c, cp, p, verification_feedback=None: _fake_fix())
    monkeypatch.setattr(orch, "validate_diff", lambda d, r=None: ScopeCheckResult(rejected=False, reasons=[]))
    monkeypatch.setattr(orch, "check_diff", lambda d, failing_test_names=None: AntiCheatResult(
        rejected=False, reject_reasons=[], requires_human_review=False, review_reasons=[]))
    _patch_verifier(monkeypatch, lambda cp, d: _fake_verification(passed=True, delta="0 failed"))

    state = _base_state()
    state["context"] = load_fixture("flaky-test")
    state["checkout_path"] = flaky_checkout

    final_state = build_graph().invoke(state)

    assert isinstance(final_state["retry_reproduced"], bool)
    if final_state["retry_reproduced"]:
        assert "diagnosis" in final_state, "a reproducing flake is a real failure and must be diagnosed"
        assert "confirmed flake" not in orch.describe_outcome(final_state)
    else:
        assert "diagnosis" not in final_state, "a confirmed flake must never reach Diagnosis"
        assert "confirmed flake" in orch.describe_outcome(final_state)

def test_pr_is_not_opened_unless_explicitly_requested(monkeypatch):
    """Opening a PR is a side effect on a real repository. A plain demo run
    must never cause one (DECISIONS.md #31).
    """
    _mock_happy_path(monkeypatch)

    def never_called(*a, **kw):
        raise AssertionError("create_pull_request must not run without --open-pr")

    import agent.github
    monkeypatch.setattr(agent.github, "create_pull_request", never_called)

    final_state = build_graph().invoke(_base_state())

    assert final_state["confidence"] == "HIGH"
    assert "pr_url" not in final_state


def test_pr_is_opened_when_requested_and_verification_passed(monkeypatch):
    _mock_happy_path(monkeypatch)

    import agent.github
    monkeypatch.setattr(
        agent.github, "create_pull_request",
        lambda *a, **kw: "https://github.com/tony-darco/sample-app/pull/1",
    )

    state = _base_state()
    state["open_pr_enabled"] = True
    final_state = build_graph().invoke(state)

    assert final_state["pr_url"].endswith("/pull/1")
    assert "PR opened for review" in orch.describe_outcome(final_state)


def test_failed_verification_never_opens_a_pr_even_when_requested(monkeypatch):
    """The unresolved path must not reach open_pr at all -- a fix that did
    not verify is exactly what must never reach a reviewer as a proposal.
    """
    _mock_happy_path(monkeypatch)
    _patch_verifier(monkeypatch, lambda c, d: _fake_verification(passed=False, delta="still failing"))

    import agent.github
    def never_called(*a, **kw):
        raise AssertionError("a failed verification must never open a PR")
    monkeypatch.setattr(agent.github, "create_pull_request", never_called)

    state = _base_state()
    state["open_pr_enabled"] = True
    final_state = build_graph().invoke(state)

    assert "pr_url" not in final_state
    assert "unresolved" in orch.describe_outcome(final_state)
