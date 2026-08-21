import pytest
from pydantic import ValidationError

from agent.trace import TraceEvent, inputs_hash


def _event(**overrides):
    defaults = dict(
        timestamp="2026-08-21T00:00:00+00:00",
        actor="triage",
        decision="classified as CODE_DEFECT",
        reasoning="assertion failure in test_ten_percent_discount points at discounts.py",
        inputs_hash=inputs_hash({"a": 1}),
    )
    defaults.update(overrides)
    return TraceEvent(**defaults)


def test_valid_event_constructs():
    event = _event()
    assert event.actor == "triage"


def test_empty_reasoning_raises():
    with pytest.raises(ValidationError):
        _event(reasoning="")


def test_whitespace_only_reasoning_raises():
    with pytest.raises(ValidationError):
        _event(reasoning="   \n\t  ")


def test_inputs_hash_is_deterministic():
    a = inputs_hash({"x": 1, "y": [1, 2, 3]})
    b = inputs_hash({"y": [1, 2, 3], "x": 1})
    assert a == b


def test_inputs_hash_differs_for_different_inputs():
    assert inputs_hash({"x": 1}) != inputs_hash({"x": 2})
