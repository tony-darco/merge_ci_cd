from agent.guards.redaction import redact
from agent.tests.fixtures import load_fixture


def test_redacts_fake_aws_key_planted_in_config_secret_fixture():
    ctx = load_fixture("config-secret")
    raw_log = next(iter(ctx.logs.values()))
    assert "AKIAIOSFODNN7EXAMPLE" in raw_log, "fixture should still contain the planted fake key pre-redaction"

    redacted = redact(raw_log)
    assert "AKIAIOSFODNN7EXAMPLE" not in redacted
    assert "[REDACTED]" in redacted


def test_redacts_github_token():
    text = "auth header: ghp_" + "a" * 36
    assert "ghp_" not in redact(text)


def test_redacts_bearer_token():
    text = "Authorization: Bearer sk-abcdEFGH12345678"
    assert "sk-abcdEFGH12345678" not in redact(text)


def test_redacts_private_key_block():
    text = "-----BEGIN RSA PRIVATE KEY-----\nMIIB...fakekeydata...\n-----END RSA PRIVATE KEY-----"
    redacted = redact(text)
    assert "MIIB" not in redacted


def test_leaves_ordinary_log_text_untouched():
    text = "FAILED tests/test_discounts.py::test_ten_percent_discount - assert 0.9 == 90.0"
    assert redact(text) == text
