from agent.agents.diagnosis import run_diagnosis
from agent.guards.cascade_filter import select_root_failure
from agent.llm.providers.ollama import OllamaProvider
from agent.tests.fakes import NeverCalledProvider
from agent.tests.fixtures import load_fixture


def test_code_defect_diagnosis_cites_evidence_and_affected_file():
    ctx = load_fixture("code-defect")
    root = select_root_failure(ctx.failed_nodes)
    result = run_diagnosis(ctx, root, OllamaProvider())

    assert result.root_cause and result.root_cause != "insufficient evidence"
    assert "discounts.py" in "".join(result.affected_files)
    assert len(result.evidence) > 0, "a hypothesis with no log line backing it must be rejected"
    assert any("0.9" in e.excerpt or "90.0" in e.excerpt for e in result.evidence)


def test_empty_log_degrades_to_insufficient_evidence_without_llm_call():
    ctx = load_fixture("infra-failure")  # real captured fixture with an empty log
    root = select_root_failure(ctx.failed_nodes)
    result = run_diagnosis(ctx, root, NeverCalledProvider())

    assert result.root_cause == "insufficient evidence"
    assert result.evidence == []
