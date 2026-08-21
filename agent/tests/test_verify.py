"""M3 exit checks: a real fix diff verifies clean, a diff that doesn't
actually fix the bug fails verification, and the image is built at most
once across repeated calls (DECISIONS.md #15) -- proven by spying on
subprocess.run, not assumed from the code.
"""

import subprocess
import tempfile
from pathlib import Path

import pytest

import agent.verifiers.docker as docker_verifier_module
from agent.agents.fix import _unified_diff_for
from agent.agents.verify import run_verification
from agent.verifiers.docker import DockerVerifier

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_APP_DIR = REPO_ROOT / "sample-app"


@pytest.fixture
def code_defect_checkout():
    with tempfile.TemporaryDirectory(prefix="test-verify-") as scratch:
        subprocess.run(
            ["git", "-C", str(SAMPLE_APP_DIR), "worktree", "add", "--detach", scratch, "seed/code-defect"],
            check=True, capture_output=True, text=True,
        )
        try:
            yield Path(scratch)
        finally:
            subprocess.run(
                ["git", "-C", str(SAMPLE_APP_DIR), "worktree", "remove", "--force", scratch],
                check=False, capture_output=True, text=True,
            )


def _real_fix_diff(checkout_path: Path) -> str:
    old = (checkout_path / "src/sample_app/discounts.py").read_text()
    new = old.replace("    return result / 100", "    return result")
    assert new != old
    return _unified_diff_for("src/sample_app/discounts.py", old, new)


def _wrong_fix_diff(checkout_path: Path) -> str:
    old = (checkout_path / "src/sample_app/discounts.py").read_text()
    new = old.replace(
        "    if not 0 <= pct <= 100:",
        "    # does not touch the divide-by-100-twice bug\n    if not 0 <= pct <= 100:",
    )
    assert new != old
    return _unified_diff_for("src/sample_app/discounts.py", old, new)


def test_real_fix_passes_verification(code_defect_checkout):
    diff = _real_fix_diff(code_defect_checkout)
    result = run_verification(code_defect_checkout, diff)
    assert result.passed is True
    assert result.regressions == []
    assert result.patched_summary.failed_tests == []


def test_wrong_fix_fails_verification(code_defect_checkout):
    diff = _wrong_fix_diff(code_defect_checkout)
    result = run_verification(code_defect_checkout, diff)
    assert result.passed is False
    assert "tests.test_discounts::test_ten_percent_discount" in result.patched_summary.failed_tests


def test_image_built_at_most_once_across_calls(code_defect_checkout, monkeypatch):
    verifier = DockerVerifier()
    assert verifier._image_built is False
    diff = _real_fix_diff(code_defect_checkout)

    verifier.run(code_defect_checkout, diff)
    assert verifier._image_built is True

    original_run = subprocess.run

    def spy(args, *a, **kw):
        assert not (args[0] == "docker" and args[1] == "build"), "docker build ran on a second verification call"
        return original_run(args, *a, **kw)

    monkeypatch.setattr(docker_verifier_module.subprocess, "run", spy)
    verifier.run(code_defect_checkout, diff)
