"""Deterministic pre-LLM check (spec §7.1): infrastructure masquerading as
a code failure -- OOMKilled, disk pressure, network timeout, etc. -- must be
caught by exit code/message pattern before any LLM reasoning, not after.
"""

from agent.llm.schema import FailureContext, TriageResult

INFRA_PATTERNS = [
    "oomkilled",
    "out of memory",
    "no space left on device",
    "connection refused",
    "imagepullbackoff",
    "image pull backoff",
    "node not ready",
    "evicted",
    "disk pressure",
]


def detect_infra_failure(context: FailureContext) -> TriageResult | None:
    haystack = " ".join(
        [n.message.lower() for n in context.failed_nodes] + [log.lower() for log in context.logs.values()]
    )
    for pattern in INFRA_PATTERNS:
        if pattern in haystack:
            return TriageResult(
                category="INFRA_FAILURE",
                reasoning=(
                    f"deterministic infra-failure pattern {pattern!r} matched in node "
                    "message/logs -- bypassing the LLM entirely (spec §7.1)"
                ),
                evidence_summary=pattern,
            )
    return None
