"""M6 checks. The PR body is assembled from recorded TraceEvents, so these
assert the reviewer-facing content is actually present -- a body missing
its disclaimer or its evidence is a real defect, not a cosmetic one, since
the disclaimer is the mechanism by which decision #6's human-in-the-loop
promise reaches the person who has to act on it.

The live test that opens a real PR is marked `live` and deselected by
default, matching how the Docker/cluster-dependent suites are handled.
"""

import pytest

from agent.github import DISCLAIMER, branch_name_for, build_pr_body
from agent.llm.schema import (
    DiagnosisResult,
    EvidenceCitation,
    FixResult,
    TestRunSummary,
    VerificationResult,
)
from agent.tests.fixtures import load_fixture
from agent.trace import TraceEvent, now


def _diagnosis(alternative: str = "") -> DiagnosisResult:
    return DiagnosisResult(
        root_cause="apply_percentage_discount divides by 100 twice",
        evidence=[EvidenceCitation(source="log", excerpt="assert 0.9 == 90.0", line_range=None)],
        alternative_hypothesis=alternative,
        affected_files=["src/sample_app/discounts.py"],
        category="CODE_DEFECT",
    )


def _fix() -> FixResult:
    return FixResult(
        diff="--- a/src/sample_app/discounts.py\n+++ b/src/sample_app/discounts.py\n",
        rationale="Return the discounted amount instead of dividing it by 100 a second time.",
        blast_radius="1 file, 1 line",
        lockfile_change_reason=None,
    )


def _verification() -> VerificationResult:
    return VerificationResult(
        baseline_summary=TestRunSummary(passed_tests=["t_ok"], failed_tests=["t_bad"]),
        patched_summary=TestRunSummary(passed_tests=["t_ok", "t_bad"], failed_tests=[]),
        delta="1 failed -> 0 failed",
        passed=True,
        regressions=[],
        newly_passing=["t_bad"],
    )


def _events() -> list[TraceEvent]:
    return [
        TraceEvent(
            timestamp=now(), actor="triage", decision="classified as CODE_DEFECT",
            reasoning="assertion mismatch in application code", inputs_hash="abc",
            model="qwen3.5:0.8b",
        ),
        TraceEvent(
            timestamp=now(), actor="verify", decision="verification passed: 1 failed -> 0 failed",
            reasoning="no regressions, all tests green", inputs_hash="def",
        ),
    ]


def _body(confidence: str = "HIGH", alternative: str = "") -> str:
    return build_pr_body(
        load_fixture("code-defect"), _diagnosis(alternative), _fix(),
        _verification(), confidence, _events(),
    )


def test_body_carries_the_disclaimer_verbatim():
    assert DISCLAIMER in _body()


def test_body_cites_root_cause_and_evidence():
    body = _body()
    assert "divides by 100 twice" in body
    assert "assert 0.9 == 90.0" in body, "the cited log line must reach the reviewer"


def test_body_describes_the_actual_verification_environment(monkeypatch):
    """The body must not claim sandbox isolation it did not have: the same
    sentence is true of the Argo verifier and false of the local Docker one.
    """
    import agent.config
    monkeypatch.setattr(agent.config, "VERIFIER", "docker")
    docker_body = _body()
    assert "not network-isolated" in docker_body.replace("**", "")
    assert "default-deny egress" not in docker_body, "must not claim isolation Docker never had"

    monkeypatch.setattr(agent.config, "VERIFIER", "argo")
    argo_body = _body()
    assert "default-deny egress" in argo_body
    assert "briefly predate enforcement" in argo_body, "the known race must be disclosed, not hidden"


def test_body_reports_verification_and_confidence_with_a_caveat():
    body = _body()
    assert "1 failed -> 0 failed" in body
    assert "Confidence: HIGH" in body
    assert "not a substitute" in body, "a confidence tier must never appear without its caveat"


def test_low_confidence_says_so_plainly():
    body = _body(confidence="LOW")
    assert "should not be merged" in body


def test_body_renders_the_decision_trace():
    body = _body()
    assert "classified as CODE_DEFECT" in body
    assert "qwen3.5:0.8b" in body, "the trace must record which model actually decided"


def test_body_states_when_no_alternative_was_considered():
    assert "No competing hypothesis" in _body()
    assert "memory pressure" in _body(alternative="memory pressure")


def test_branch_name_is_scoped_to_the_run():
    context = load_fixture("code-defect")
    branch = branch_name_for(context)
    assert branch.startswith("agentic-fix/")
    assert context.commit_sha[:8] in branch


@pytest.mark.live
def test_full_run_opens_a_real_pr():
    """Opens a genuine PR on the real repository. Deselected by default."""
    import json
    import subprocess

    from agent.orchestrator import run_orchestrator

    state = run_orchestrator("code-defect", open_pr=True)
    url = state.get("pr_url")
    assert url, "a verified fix with --open-pr must produce a PR URL"

    viewed = json.loads(subprocess.run(
        ["gh", "pr", "view", url, "--json", "state,title"],
        check=True, capture_output=True, text=True,
    ).stdout)
    assert viewed["state"] == "OPEN", "the PR must be left open for a human, never merged"
