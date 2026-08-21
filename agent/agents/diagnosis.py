"""Diagnosis: root cause hypothesis + cited evidence (spec §5.2). Must cite
evidence -- a hypothesis with no log line backing it is rejected. Degrades
to "insufficient evidence" rather than hallucinating when the log is empty
or too short to reason over.
"""

from agent.config import DIAGNOSIS_MODEL
from agent.context.log_slicer import slice_log
from agent.guards.evidence_check import has_sufficient_evidence
from agent.guards.redaction import redact
from agent.llm.interface import LLMProvider
from agent.llm.schema import DiagnosisResult, FailedNode, FailureContext
from agent.trace import TraceEvent, inputs_hash, now, record_trace


def run_diagnosis(context: FailureContext, root_node: FailedNode, provider: LLMProvider) -> DiagnosisResult:
    raw_log = context.logs.get(root_node.name, "")
    redacted_log = redact(raw_log)

    # Check sufficiency on the raw redacted log, not the sliced+delimiter-
    # wrapped prompt text -- the wrapper's boilerplate alone would clear a
    # naive length check even for a genuinely empty log.
    if not has_sufficient_evidence(redacted_log):
        result = DiagnosisResult(
            root_cause="insufficient evidence",
            evidence=[],
            alternative_hypothesis="",
            affected_files=[],
            category="UNKNOWN",
        )
        record_trace(TraceEvent(
            timestamp=now(),
            actor="diagnosis",
            decision="insufficient evidence, no hypothesis formed",
            reasoning="redacted log is empty or too short to support a root-cause hypothesis without hallucinating",
            evidence=[],
            alternatives_rejected=["LLM diagnosis skipped -- no log content to reason over"],
            inputs_hash=inputs_hash({"root_node": root_node.model_dump()}),
        ))
        return result

    sliced = slice_log(redacted_log, DIAGNOSIS_MODEL)
    prompt = _build_prompt(context.changed_files, sliced)
    result, meta = provider.generate_structured(DIAGNOSIS_MODEL, prompt, DiagnosisResult)

    record_trace(TraceEvent(
        timestamp=now(),
        actor="diagnosis",
        decision=f"root cause: {result.root_cause}",
        reasoning=(
            f"cited {len(result.evidence)} evidence citation(s); "
            f"alternative hypothesis: {result.alternative_hypothesis or 'none considered'}"
        ),
        evidence=[e.excerpt for e in result.evidence],
        alternatives_rejected=[result.alternative_hypothesis] if result.alternative_hypothesis else [],
        inputs_hash=inputs_hash({"root_node": root_node.model_dump(), "changed_files": context.changed_files}),
        model=DIAGNOSIS_MODEL,
        provider=meta.get("provider"),
        tokens=meta.get("tokens"),
        latency=meta.get("latency"),
    ))
    return result


def _build_prompt(changed_files: list[str], sliced_log: str) -> str:
    return f"""You are a diagnosis agent for a CI failure. Given the failing log and the files changed in the triggering commit, produce a root-cause hypothesis.

You MUST cite evidence: quote the specific log line(s) that support your hypothesis. A hypothesis with no log line backing it will be rejected.

Changed files: {changed_files}

{sliced_log}

Return JSON matching this schema exactly:
{{"root_cause": "<one sentence root cause>", "evidence": [{{"source": "log", "excerpt": "<quoted log line>", "line_range": null}}], "alternative_hypothesis": "<a plausible alternative, or empty string if none>", "affected_files": ["<file path>", "..."], "category": "CODE_DEFECT"}}
"""
