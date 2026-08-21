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
