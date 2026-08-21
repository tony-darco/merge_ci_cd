"""Deterministic pre-LLM check, sibling to infra_detector.py (DECISIONS.md
#17): expired/missing credentials must never reach the LLM classifier --
that guarantee shouldn't hinge on a 0.8B model classifying correctly.
"""

import re

from agent.llm.schema import FailureContext, TriageResult

_PHRASE_PATTERNS = [
    "authentication failed",
    "invalid credentials",
    "missing required environment variable",
    "permission denied",
]
_CODE_PATTERNS = [re.compile(r"\b401\b"), re.compile(r"\b403\b")]


def detect_config_or_secret(context: FailureContext) -> TriageResult | None:
    haystack = " ".join(
        [n.message.lower() for n in context.failed_nodes] + [log.lower() for log in context.logs.values()]
    )
    for phrase in _PHRASE_PATTERNS:
        if phrase in haystack:
            return TriageResult(
                category="CONFIG_OR_SECRET",
                reasoning=(
                    f"deterministic config/secret pattern {phrase!r} matched in node "
                    "message/logs -- bypassing the LLM entirely (DECISIONS.md #17)"
                ),
                evidence_summary=phrase,
            )
    for pattern in _CODE_PATTERNS:
        if pattern.search(haystack):
            return TriageResult(
                category="CONFIG_OR_SECRET",
                reasoning=(
                    f"deterministic config/secret pattern {pattern.pattern!r} matched in "
                    "node message/logs -- bypassing the LLM entirely (DECISIONS.md #17)"
                ),
                evidence_summary=pattern.pattern,
            )
    return None
