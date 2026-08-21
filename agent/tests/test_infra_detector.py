from agent.guards.infra_detector import detect_infra_failure
from agent.tests.fixtures import load_fixture


def test_matches_real_captured_oom_fixture():
    ctx = load_fixture("infra-failure")
    result = detect_infra_failure(ctx)
    assert result is not None
    assert result.category == "INFRA_FAILURE"


def test_returns_none_for_unrelated_failure():
    ctx = load_fixture("code-defect")
    assert detect_infra_failure(ctx) is None
