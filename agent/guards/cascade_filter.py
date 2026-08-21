"""Cascading failures (spec §7.1): one root failure can fail several
downstream DAG nodes. Diagnose only the earliest failure -- never open
multiple PRs for one root cause.
"""

from agent.llm.schema import FailedNode


def select_root_failure(failed_nodes: list[FailedNode]) -> FailedNode:
    if not failed_nodes:
        raise ValueError("no failed nodes to select from")
    return sorted(failed_nodes, key=lambda n: n.finished_at or "")[0]
