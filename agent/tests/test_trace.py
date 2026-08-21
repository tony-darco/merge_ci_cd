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


# M7: the trace validator is the last line of defense, but it should rarely
# be the one that fires. Empty reasoning is caught at the schema boundary so
# generate_structured retries the model instead of crashing the run at
# record_trace time (observed live with qwen3.5:0.8b -- see LOG.md).
@pytest.mark.parametrize("empty", ["", "   ", "\n\t "])
def test_agent_schemas_reject_empty_reasoning_before_it_reaches_the_trace(empty):
    import pydantic

    from agent.llm.schema import TriageResult

    with pytest.raises(pydantic.ValidationError):
        TriageResult(category="CODE_DEFECT", reasoning=empty, evidence_summary="x")


def test_schema_rejection_message_tells_the_model_what_to_fix():
    """generate_structured feeds the validation error back to the model, so
    the message has to be actionable, not just a type name.
    """
    import pydantic

    from agent.llm.schema import TriageResult

    try:
        TriageResult(category="CODE_DEFECT", reasoning="", evidence_summary="x")
    except pydantic.ValidationError as e:
        assert "reasoning" in str(e)
        assert "at least 1 character" in str(e)
