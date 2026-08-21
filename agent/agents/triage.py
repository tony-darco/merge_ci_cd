"""Triage: the gatekeeper (spec §5.1). Only CODE_DEFECT/DEPENDENCY_ISSUE
proceed to Diagnosis/Fix -- everything else exits with a diagnosis and no
fix attempt. Deterministic detectors run before any LLM call so the system
never "confidently fixes" an OOMKill or an auth failure.
"""

from agent.config import TRIAGE_FALLBACK_MODEL, TRIAGE_MODEL
from agent.context.log_slicer import slice_log
from agent.guards.cascade_filter import select_root_failure
from agent.guards.infra_detector import detect_infra_failure
from agent.guards.redaction import redact
from agent.guards.secret_detector import detect_config_or_secret
from agent.llm.interface import LLMProvider, SchemaValidationFailure
from agent.llm.schema import FailureContext, TriageResult
from agent.trace import TraceEvent, inputs_hash, now, record_trace

_DETECTORS = (detect_infra_failure, detect_config_or_secret)


def run_triage(context: FailureContext, provider: LLMProvider) -> TriageResult:
    root_node = select_root_failure(context.failed_nodes)
    root_log = context.logs.get(root_node.name, "")
    scoped = context.model_copy(update={"failed_nodes": [root_node], "logs": {root_node.name: root_log}})

    for detector in _DETECTORS:
        result = detector(scoped)
        if result is not None:
            _trace_result(result, scoped, model=None, provider=None, tokens=None, latency=None, deterministic=True)
            return result

    sliced = slice_log(redact(root_log), TRIAGE_MODEL)
    prompt = _build_prompt(root_node.message, sliced)

    model_used = TRIAGE_MODEL
    try:
        result, meta = provider.generate_structured(TRIAGE_MODEL, prompt, TriageResult)
    except SchemaValidationFailure:
        # spec/DECISIONS.md #16: escalate once to the stronger model rather
        # than giving up when the small model can't produce valid JSON.
        model_used = TRIAGE_FALLBACK_MODEL
        result, meta = provider.generate_structured(TRIAGE_FALLBACK_MODEL, prompt, TriageResult)

    _trace_result(
        result, scoped, model=model_used, provider=meta.get("provider"),
        tokens=meta.get("tokens"), latency=meta.get("latency"), deterministic=False,
    )
    return result


def _trace_result(
    result: TriageResult, scoped: FailureContext, *, model, provider, tokens, latency, deterministic: bool
) -> None:
    record_trace(TraceEvent(
        timestamp=now(),
        actor="triage",
        decision=f"classified as {result.category}",
        reasoning=result.reasoning,
        evidence=[result.evidence_summary],
        alternatives_rejected=(
            ["LLM classification skipped -- deterministic detector matched first"] if deterministic else []
        ),
        inputs_hash=inputs_hash(scoped.model_dump()),
        model=model,
        provider=provider,
        tokens=tokens,
        latency=latency,
    ))


def _build_prompt(node_message: str, sliced_log: str) -> str:
    return f"""You are a CI failure triage classifier. Classify this failure into exactly one category: CODE_DEFECT, DEPENDENCY_ISSUE, INFRA_FAILURE, FLAKY, CONFIG_OR_SECRET, or UNKNOWN.

- CODE_DEFECT: a bug in application source code (assertion failures, logic errors, exceptions from application code).
- DEPENDENCY_ISSUE: a missing or broken third-party dependency.
- INFRA_FAILURE: resource exhaustion, scheduling, networking, or other cluster/infra problems.
- FLAKY: intermittent, non-deterministic failure unrelated to the code change.
- CONFIG_OR_SECRET: missing, expired, or invalid credentials/configuration.
- UNKNOWN: none of the above clearly applies.

Node message: {node_message}

{sliced_log}

Return JSON matching this schema exactly:
{{"category": "<one of the six values above>", "reasoning": "<why, citing specific evidence>", "evidence_summary": "<a short quoted excerpt from the log supporting your classification>"}}
"""
