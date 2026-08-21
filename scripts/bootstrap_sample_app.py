#!/usr/bin/env python3
"""Recreates sample-app/ from scratch.

sample-app/ is a separate, gitignored git repo (DECISIONS.md #10) -- it has
its own commit history and branches so that seed branches fork only the
victim app, never this repo's agent code. It has no remote, so a fresh
`git clone` of this repo does not include it. Every file this script writes
is what M0 originally hand-built directly against a live cluster; this just
makes that reproducible for anyone besides the machine it was first built
on.

Usage: python scripts/bootstrap_sample_app.py
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_APP_DIR = REPO_ROOT / "sample-app"

MAIN_FILES = {
    ".gitignore": """.venv*/
__pycache__/
*.egg-info/
*.pyc
""",
    "Dockerfile": """FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN pip install --no-cache-dir -e .
CMD ["pytest", "-q"]
""",
    "pyproject.toml": """[project]
name = "sample-app"
version = "0.1.0"
description = "Sample invoice line-item calculator used as the Agentic CI/CD Fixer's target codebase"
requires-python = ">=3.13"
dependencies = []

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
""",
    "requirements.txt": "pytest>=8\n",
    "src/sample_app/__init__.py": "",
    "src/sample_app/discounts.py": """def apply_percentage_discount(amount: float, pct: float) -> float:
    if not 0 <= pct <= 100:
        raise ValueError(f"discount percentage must be between 0 and 100, got {pct}")
    return amount * (1 - pct / 100)
""",
    "src/sample_app/external_client.py": '''import os

_VALID_TOKEN = "valid-token-for-tests"
_RATES = {"USD": 1.0, "EUR": 0.92}


class AuthenticationError(RuntimeError):
    pass


def get_api_token() -> str:
    token = os.environ.get("API_TOKEN")
    if not token:
        raise AuthenticationError("missing required environment variable: API_TOKEN")
    return token


def fetch_exchange_rate(currency: str) -> float:
    token = get_api_token()
    if token != _VALID_TOKEN:
        raise AuthenticationError("authentication failed: invalid credentials")
    if currency not in _RATES:
        raise ValueError(f"unsupported currency: {currency}")
    return _RATES[currency]
''',
    "src/sample_app/formatting.py": """def round_currency(amount: float) -> float:
    return round(amount, 2)
""",
    "src/sample_app/pricing.py": """from sample_app.discounts import apply_percentage_discount
from sample_app.formatting import round_currency


def calculate_line_total(qty: int, unit_price: float, discount_pct: float) -> float:
    subtotal = qty * unit_price
    discounted = apply_percentage_discount(subtotal, discount_pct)
    return round_currency(discounted)
""",
    "tests/__init__.py": "",
    "tests/test_discounts.py": """import pytest

from sample_app.discounts import apply_percentage_discount


def test_ten_percent_discount():
    assert apply_percentage_discount(100.0, 10) == 90.0


def test_zero_percent_discount():
    assert apply_percentage_discount(50.0, 0) == 50.0


def test_full_discount():
    assert apply_percentage_discount(50.0, 100) == 0.0


def test_invalid_discount_raises():
    with pytest.raises(ValueError):
        apply_percentage_discount(50.0, 150)
""",
    "tests/test_external_client.py": '''import pytest

from sample_app.external_client import AuthenticationError, fetch_exchange_rate, get_api_token


def test_fetch_usd_rate(monkeypatch):
    monkeypatch.setenv("API_TOKEN", "valid-token-for-tests")
    assert fetch_exchange_rate("USD") == 1.0


def test_missing_token_raises(monkeypatch):
    monkeypatch.delenv("API_TOKEN", raising=False)
    with pytest.raises(AuthenticationError, match="missing required environment variable"):
        get_api_token()


def test_invalid_token_raises(monkeypatch):
    monkeypatch.setenv("API_TOKEN", "wrong-token")
    with pytest.raises(AuthenticationError, match="authentication failed"):
        fetch_exchange_rate("USD")


def test_unsupported_currency_raises(monkeypatch):
    monkeypatch.setenv("API_TOKEN", "valid-token-for-tests")
    with pytest.raises(ValueError, match="unsupported currency"):
        fetch_exchange_rate("GBP")
''',
    "tests/test_formatting.py": """from sample_app.formatting import round_currency


def test_round_currency_rounds_down():
    assert round_currency(12.344) == 12.34


def test_round_currency_rounds_up():
    assert round_currency(12.346) == 12.35


def test_round_currency_handles_integers():
    assert round_currency(20) == 20.0
""",
    "tests/test_pricing.py": """from sample_app.pricing import calculate_line_total


def test_calculate_line_total_no_discount():
    assert calculate_line_total(3, 10.0, 0) == 30.0


def test_calculate_line_total_with_discount():
    assert calculate_line_total(2, 50.0, 10) == 90.0


def test_calculate_line_total_rounds_result():
    assert calculate_line_total(3, 3.333, 0) == 10.0
""",
}

M0_BAD_IMPORT_FORMATTING = """import jsonn


def round_currency(amount: float) -> float:
    return round(amount, 2)
"""

CODE_DEFECT_DISCOUNTS = """def apply_percentage_discount(amount: float, pct: float) -> float:
    if not 0 <= pct <= 100:
        raise ValueError(f"discount percentage must be between 0 and 100, got {pct}")
    result = amount * (1 - pct / 100)
    return result / 100
"""

FLAKY_TEST_CONTENT = """import random


def test_probabilistic_rounding_edge_case():
    # Seeded flaky test (see DECISIONS.md #19): fails ~15% of the time by
    # construction, to exercise the triage flake-retry path. Not a real
    # assertion about rounding behavior.
    assert random.random() > 0.15
"""

CONFIG_SECRET_TEST_CONTENT = """from sample_app.external_client import fetch_exchange_rate

# Seed for the CONFIG_OR_SECRET triage category (see DECISIONS.md #17, #22).
# Deliberately relies on the ambient API_TOKEN environment variable rather
# than monkeypatching it, unlike test_external_client.py's unit tests: this
# test simulates a pipeline whose secret injection is missing or wrong.
# Only present on this branch, so it never affects other seeds' pipeline runs.


def test_fetch_usd_rate_requires_real_token():
    assert fetch_exchange_rate("USD") == 1.0
"""


def _run(args: list[str]) -> None:
    subprocess.run(args, cwd=SAMPLE_APP_DIR, check=True, capture_output=True, text=True)


def _write(rel_path: str, content: str) -> None:
    path = SAMPLE_APP_DIR / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def main() -> None:
    if SAMPLE_APP_DIR.exists():
        print(f"{SAMPLE_APP_DIR} already exists -- refusing to overwrite. Remove it first for a clean rebuild.")
        sys.exit(1)

    SAMPLE_APP_DIR.mkdir()
    _run(["git", "init", "-q"])
    _run(["git", "checkout", "-q", "-b", "main"])
    for rel_path, content in MAIN_FILES.items():
        _write(rel_path, content)
    _run(["git", "add", "-A"])
    _run(["git", "-c", "user.email=bootstrap@local", "-c", "user.name=bootstrap",
          "commit", "-q", "-m", "invoice line-item calculator: pricing, discounts, formatting, external_client"])

    _run(["git", "checkout", "-q", "-b", "seed/m0-bad-import"])
    _write("src/sample_app/formatting.py", M0_BAD_IMPORT_FORMATTING)
    _run(["git", "-c", "user.email=bootstrap@local", "-c", "user.name=bootstrap",
          "commit", "-q", "-am", "seed: typo'd import crashes formatting.py at collection time"])

    _run(["git", "checkout", "-q", "main"])
    _run(["git", "checkout", "-q", "-b", "seed/code-defect"])
    _write("src/sample_app/discounts.py", CODE_DEFECT_DISCOUNTS)
    _run(["git", "-c", "user.email=bootstrap@local", "-c", "user.name=bootstrap",
          "commit", "-q", "-am", "seed: apply_percentage_discount divides by 100 twice (assertion mismatch, not a crash)"])

    # seed/infra-failure is identical to main -- the OOM comes from the
    # workflow's memory limit at submission time (manifests/sample-pipeline.yaml),
    # not a code change.
    _run(["git", "checkout", "-q", "main"])
    _run(["git", "checkout", "-q", "-b", "seed/infra-failure"])

    _run(["git", "checkout", "-q", "main"])
    _run(["git", "checkout", "-q", "-b", "seed/flaky-test"])
    _write("tests/test_flaky_seed.py", FLAKY_TEST_CONTENT)
    _run(["git", "add", "-A"])
    _run(["git", "-c", "user.email=bootstrap@local", "-c", "user.name=bootstrap",
          "commit", "-q", "-m", "seed: probabilistic test fails ~15% of the time by construction"])

    _run(["git", "checkout", "-q", "main"])
    _run(["git", "checkout", "-q", "-b", "seed/config-secret"])
    _write("tests/test_config_secret_seed.py", CONFIG_SECRET_TEST_CONTENT)
    _run(["git", "add", "-A"])
    _run(["git", "-c", "user.email=bootstrap@local", "-c", "user.name=bootstrap",
          "commit", "-q", "-m", "seed: relies on ambient API_TOKEN, simulating missing/wrong secret injection"])

    _run(["git", "checkout", "-q", "main"])
    print(
        f"sample-app bootstrapped at {SAMPLE_APP_DIR} with branches: "
        "main, seed/m0-bad-import, seed/code-defect, seed/infra-failure, seed/flaky-test, seed/config-secret"
    )


if __name__ == "__main__":
    main()
