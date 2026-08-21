from agent.agents.triage import run_triage
from agent.llm.providers.ollama import OllamaProvider
from agent.tests.fakes import NeverCalledProvider
from agent.tests.fixtures import load_fixture


def test_infra_failure_short_circuits_without_llm():
    ctx = load_fixture("infra-failure")
    result = run_triage(ctx, NeverCalledProvider())
    assert result.category == "INFRA_FAILURE"


def test_config_secret_short_circuits_without_llm():
    ctx = load_fixture("config-secret")
    result = run_triage(ctx, NeverCalledProvider())
    assert result.category == "CONFIG_OR_SECRET"


def test_code_defect_classifies_correctly():
    ctx = load_fixture("code-defect")
    result = run_triage(ctx, OllamaProvider())
    assert result.category == "CODE_DEFECT"


def test_flaky_classifies_correctly():
    ctx = load_fixture("flaky-test")
    result = run_triage(ctx, OllamaProvider())
    assert result.category == "FLAKY"
