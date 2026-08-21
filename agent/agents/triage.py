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
from agent.llm.schema import FIXABLE_CATEGORIES, FailureContext, TriageResult
from agent.trace import TraceEvent, inputs_hash, now, record_trace

_DETECTORS = (detect_infra_failure, detect_config_or_secret)

# Categories whose consequences are recoverable if Triage gets them wrong:
# both route onward into real work rather than ending the run. Anything
# else is a terminal refusal and gets a second opinion -- see run_triage.
_SELF_CORRECTING_CATEGORIES = FIXABLE_CATEGORIES | {"FLAKY"}


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
    escalation_reason: str | None = None
    try:
        result, meta = provider.generate_structured(TRIAGE_MODEL, prompt, TriageResult)
    except SchemaValidationFailure:
        # spec/DECISIONS.md #16: escalate once to the stronger model rather
        # than giving up when the small model can't produce valid JSON.
        escalation_reason = "primary model could not produce schema-valid output"
        result, meta = provider.generate_structured(TRIAGE_FALLBACK_MODEL, prompt, TriageResult)
        model_used = TRIAGE_FALLBACK_MODEL

    # Schema-valid but semantically wrong is the failure mode the ladder
    # above does NOT catch, and measurement showed it is not rare: the 0.8B
    # model classified the code-defect fixture correctly in only 8/12 runs,
    # while the fallback model managed 8/8 on identical input (see LOG.md).
    #
    # Escalate on the answers where being wrong is unrecoverable. A wrong
    # CODE_DEFECT/DEPENDENCY_ISSUE/FLAKY still routes into real work --
    # FLAKY in particular self-corrects, since the retry reproduces a real
    # bug and the graph proceeds to Diagnosis anyway -- but a terminal
    # refusal ends the run, so a mistake there silently drops a fixable
    # failure on the floor. Deterministic detectors already ran and did not
    # fire, so nothing corroborates this refusal yet (DECISIONS.md #34).
    if model_used == TRIAGE_MODEL and result.category not in _SELF_CORRECTING_CATEGORIES:
        escalation_reason = (
            f"primary model returned terminal category {result.category!r} that no deterministic "
            "detector corroborated -- re-checking with the stronger model before refusing"
        )
        result, meta = provider.generate_structured(TRIAGE_FALLBACK_MODEL, prompt, TriageResult)
        model_used = TRIAGE_FALLBACK_MODEL

    _trace_result(
        result, scoped, model=model_used, provider=meta.get("provider"),
        tokens=meta.get("tokens"), latency=meta.get("latency"), deterministic=False,
        escalation_reason=escalation_reason,
    )
    return result


def _trace_result(
    result: TriageResult, scoped: FailureContext, *, model, provider, tokens, latency, deterministic: bool,
    escalation_reason: str | None = None,
) -> None:
    alternatives = []
    if deterministic:
        alternatives.append("LLM classification skipped -- deterministic detector matched first")
    if escalation_reason:
        alternatives.append(escalation_reason)
    record_trace(TraceEvent(
        timestamp=now(),
        actor="triage",
        decision=f"classified as {result.category}",
        reasoning=result.reasoning,
        evidence=[result.evidence_summary],
        alternatives_rejected=alternatives,
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
