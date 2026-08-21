import pytest

from agent.guards.cascade_filter import select_root_failure
from agent.llm.schema import FailedNode


def _node(name: str, finished_at: str | None) -> FailedNode:
    return FailedNode(
        name=name, display_name=name, message="boom", template_name="test",
        phase="Failed", pod_name=name, finished_at=finished_at,
    )


def test_selects_earliest_of_multiple_failures():
    nodes = [
        _node("downstream", "2026-08-21T00:10:00Z"),
        _node("root-cause", "2026-08-21T00:05:00Z"),
        _node("also-downstream", "2026-08-21T00:12:00Z"),
    ]
    assert select_root_failure(nodes).name == "root-cause"


def test_single_node_returned_as_is():
    nodes = [_node("only-node", "2026-08-21T00:00:00Z")]
    assert select_root_failure(nodes).name == "only-node"


def test_raises_on_empty_list():
    with pytest.raises(ValueError):
        select_root_failure([])
