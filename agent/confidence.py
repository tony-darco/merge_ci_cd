"""Confidence scoring (DECISIONS.md #5): computed purely from signals
already produced elsewhere in the run -- verification result, diagnosis
ambiguity, diff size, fix-attempt count -- never from an LLM self-report.
Not yet acted on (PR creation is M6); for M4 it's computed, printed, and
recorded as a TraceEvent.
"""

from agent.llm.schema import DiagnosisResult, FixResult, VerificationResult
from agent.trace import TraceEvent, inputs_hash, now, record_trace

HIGH_CONFIDENCE_MAX_DIFF_LINES = 30


def compute_confidence(
    verification: VerificationResult,
    diagnosis: DiagnosisResult,
    fix: FixResult,
    fix_attempts: int,
) -> str:
    if not verification.passed:
        score = "LOW"
        reasoning = "verification did not pass -- no signal supports a fix here"
    else:
        unambiguous = not diagnosis.alternative_hypothesis.strip()
        single_attempt = fix_attempts <= 1
        diff_lines = fix.diff.count("\n")
        small_diff = diff_lines <= HIGH_CONFIDENCE_MAX_DIFF_LINES

        if unambiguous and single_attempt and small_diff:
            score = "HIGH"
        else:
            score = "MEDIUM"
        reasoning = (
            f"verification passed with 0 regressions; unambiguous_diagnosis={unambiguous}, "
            f"single_attempt={single_attempt} (attempts={fix_attempts}), "
            f"small_diff={small_diff} ({diff_lines} lines)"
        )

    record_trace(TraceEvent(
        timestamp=now(),
        actor="confidence",
        decision=f"confidence={score}",
        reasoning=reasoning,
        evidence=[verification.delta],
        inputs_hash=inputs_hash({
            "verification_passed": verification.passed,
            "regressions": verification.regressions,
            "fix_attempts": fix_attempts,
        }),
    ))
    return score
