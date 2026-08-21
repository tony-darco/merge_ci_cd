"""Verification backends (DECISIONS.md #27), mirroring the LLM provider
pattern: the orchestrator holds a Verifier and doesn't know or care whether
the tests run in local Docker or as a submitted Argo Workflow inside a
locked-down cluster namespace.

Every implementation is deterministic -- no LLM anywhere (DECISIONS.md #21).
"""

from abc import ABC, abstractmethod
from pathlib import Path

from agent.llm.schema import TestRunSummary, VerificationResult
from agent.trace import TraceEvent, inputs_hash, now, record_trace


class Verifier(ABC):
    name: str

    @abstractmethod
    def _run_suite(self, checkout_path: Path, diff_text: str | None) -> dict:
        """Run the suite once and return the raw results.json payload:
        {"tests": {<test_id>: "passed"|"failed"}, "patch_applied": bool}.
        `diff_text=None` means the baseline (unpatched) run.
        """

    def run(self, pre_fix_checkout: Path, diff_text: str) -> VerificationResult:
        baseline = _summarize(self._run_suite(pre_fix_checkout, None))
        patched_raw = self._run_suite(pre_fix_checkout, diff_text)
        patched = _summarize(patched_raw)

        patch_applied = patched_raw.get("patch_applied", True)
        regressions = sorted(set(baseline.passed_tests) & set(patched.failed_tests))
        newly_passing = sorted(set(baseline.failed_tests) & set(patched.passed_tests))
        passed = patch_applied and len(patched.failed_tests) == 0

        if not patch_applied:
            delta = "patch failed to apply"
        else:
            delta = (
                f"{len(baseline.failed_tests)} failed -> {len(patched.failed_tests)} failed, "
                f"{len(baseline.passed_tests)} passed -> {len(patched.passed_tests)} passed"
            )

        result = VerificationResult(
            baseline_summary=baseline,
            patched_summary=patched,
            delta=delta,
            passed=passed,
            regressions=regressions,
            newly_passing=newly_passing,
        )

        record_trace(TraceEvent(
            timestamp=now(),
            actor="verify",
            decision=f"verification {'passed' if passed else 'failed'}: {delta}",
            reasoning=(
                f"backend={self.name}, patch_applied={patch_applied}, "
                f"regressions={regressions}, remaining_failures={patched.failed_tests}"
            ),
            evidence=[delta],
            alternatives_rejected=(
                [f"regression introduced in {t!r}" for t in regressions] if regressions else []
            ),
            inputs_hash=inputs_hash({"diff": diff_text, "checkout": str(pre_fix_checkout)}),
        ))
        return result


def _summarize(raw: dict) -> TestRunSummary:
    tests = raw.get("tests", {})
    return TestRunSummary(
        passed_tests=sorted(name for name, status in tests.items() if status == "passed"),
        failed_tests=sorted(name for name, status in tests.items() if status == "failed"),
    )
