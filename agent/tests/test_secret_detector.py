from agent.guards.secret_detector import detect_config_or_secret
from agent.tests.fixtures import load_fixture


def test_matches_config_secret_fixture():
    ctx = load_fixture("config-secret")
    result = detect_config_or_secret(ctx)
    assert result is not None
    assert result.category == "CONFIG_OR_SECRET"


def test_returns_none_for_unrelated_failure():
    ctx = load_fixture("code-defect")
    assert detect_config_or_secret(ctx) is None


def test_matches_bare_401_with_word_boundary():
    ctx = load_fixture("code-defect")
    ctx = ctx.model_copy(update={"logs": {**ctx.logs, list(ctx.logs)[0]: "request failed with status 401"}})
    result = detect_config_or_secret(ctx)
    assert result is not None


def test_does_not_false_positive_on_401_inside_a_larger_number():
    ctx = load_fixture("code-defect")
    ctx = ctx.model_copy(update={"logs": {**ctx.logs, list(ctx.logs)[0]: "14012 tests collected"}})
    assert detect_config_or_secret(ctx) is None
