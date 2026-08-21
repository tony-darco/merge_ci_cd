from agent.agents.triage import run_triage
from agent.config import TRIAGE_FALLBACK_MODEL, TRIAGE_MODEL
from agent.tests.fakes import ScriptedProvider
from agent.tests.fixtures import load_fixture
from agent.trace import clear_events, get_events


def test_escalates_to_fallback_model_when_primary_fails_schema_validation():
    clear_events()
    ctx = load_fixture("code-defect")  # LLM path, not short-circuited by a deterministic detector
    provider = ScriptedProvider({
        TRIAGE_MODEL: ["not valid json"] * 3,  # exhausts generate_structured's default max_retries
        TRIAGE_FALLBACK_MODEL: [
            '{"category": "CODE_DEFECT", "reasoning": "fallback reasoning", "evidence_summary": "assert 0.9 == 90.0"}'
        ],
    })

    result = run_triage(ctx, provider)

    assert result.category == "CODE_DEFECT"
    assert provider.calls[0][0] == TRIAGE_MODEL
    assert any(model == TRIAGE_FALLBACK_MODEL for model, _ in provider.calls)

    events = [e for e in get_events() if e.actor == "triage"]
    assert events, "expected a triage TraceEvent to be recorded"
    assert events[-1].model == TRIAGE_FALLBACK_MODEL, "trace must record the model that actually produced the verdict"


def test_escalates_when_primary_returns_uncorroborated_terminal_refusal():
    """Schema-valid but semantically wrong is the failure the original
    ladder missed (LOG.md): a terminal refusal ends the run, so a wrong one
    silently drops a fixable failure. The primary here emits perfectly
    valid CONFIG_OR_SECRET on a code-defect log that no deterministic
    detector flagged -- exactly what happened in a live M5 hook run.
    """
    clear_events()
    ctx = load_fixture("code-defect")
    provider = ScriptedProvider({
        TRIAGE_MODEL: [
            '{"category": "CONFIG_OR_SECRET", "reasoning": "looks like creds", "evidence_summary": "???"}'
        ],
        TRIAGE_FALLBACK_MODEL: [
            '{"category": "CODE_DEFECT", "reasoning": "assertion mismatch", "evidence_summary": "assert 0.9 == 90.0"}'
        ],
    })

    result = run_triage(ctx, provider)

    assert result.category == "CODE_DEFECT", "the stronger model's verdict must win"
    event = [e for e in get_events() if e.actor == "triage"][-1]
    assert event.model == TRIAGE_FALLBACK_MODEL
    assert any("terminal category" in a for a in event.alternatives_rejected)


def test_does_not_escalate_on_a_recoverable_category():
    """FLAKY self-corrects downstream (the retry reproduces and the graph
    proceeds), so it must NOT burn a second, larger-model call.
    """
    clear_events()
    ctx = load_fixture("code-defect")
    provider = ScriptedProvider({
        TRIAGE_MODEL: [
            '{"category": "FLAKY", "reasoning": "intermittent", "evidence_summary": "???"}'
        ],
    })

    result = run_triage(ctx, provider)

    assert result.category == "FLAKY"
    models_called = [model for model, _prompt in provider.calls]
    assert models_called == [TRIAGE_MODEL], "must not escalate on a self-correcting category"
