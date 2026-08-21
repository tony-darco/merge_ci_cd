from agent.guards.flake_retry import should_proceed_to_diagnosis_after_retry, should_retry_before_diagnosis
from agent.llm.schema import TriageResult


def test_flaky_category_triggers_retry():
    result = TriageResult(category="FLAKY", reasoning="looks flaky", evidence_summary="random.random()")
    assert should_retry_before_diagnosis(result) is True


def test_non_flaky_category_does_not_trigger_retry():
    result = TriageResult(category="CODE_DEFECT", reasoning="real bug", evidence_summary="assert 0.9 == 90.0")
    assert should_retry_before_diagnosis(result) is False


def test_retry_that_reproduces_proceeds_to_diagnosis():
    assert should_proceed_to_diagnosis_after_retry(retry_reproduced=True) is True


def test_retry_that_passes_stops_as_confirmed_flake():
    assert should_proceed_to_diagnosis_after_retry(retry_reproduced=False) is False
