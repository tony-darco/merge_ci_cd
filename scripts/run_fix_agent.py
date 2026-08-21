#!/usr/bin/env python3
"""Manual single-agent driver: diagnosis + fix + guards against a fixture.

Usage: uv run scripts/run_fix_agent.py --seed code-defect

Predates agent/orchestrator.py (M4) but stays useful for iterating on just
the Fix Agent without running the whole graph. Checks out the seed into a
scratch worktree so the developer's sample-app working tree is untouched.
"""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_APP_DIR = REPO_ROOT / "sample-app"
OUT_DIR = REPO_ROOT / "out"

sys.path.insert(0, str(REPO_ROOT))

from agent.agents.diagnosis import run_diagnosis  # noqa: E402
from agent.agents.fix import run_fix  # noqa: E402
from agent.guards.anticheat import check_diff  # noqa: E402
from agent.guards.cascade_filter import select_root_failure  # noqa: E402
from agent.guards.scope import validate_diff  # noqa: E402
from agent.llm.providers.ollama import OllamaProvider  # noqa: E402
from agent.tests.fixtures import load_fixture  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", required=True)
    args = parser.parse_args()
    seed = args.seed
    branch = f"seed/{seed}"

    context = load_fixture(seed)
    provider = OllamaProvider()
    root = select_root_failure(context.failed_nodes)
    diagnosis = run_diagnosis(context, root, provider)
    print(f"diagnosis root_cause: {diagnosis.root_cause}")
    print(f"diagnosis affected_files: {diagnosis.affected_files}")

    with tempfile.TemporaryDirectory(prefix=f"fix-agent-{seed}-") as scratch:
        subprocess.run(
            ["git", "-C", str(SAMPLE_APP_DIR), "worktree", "add", "--detach", scratch, branch],
            check=True, capture_output=True, text=True,
        )
        try:
            fix = run_fix(diagnosis, context, Path(scratch), provider)
        finally:
            subprocess.run(
                ["git", "-C", str(SAMPLE_APP_DIR), "worktree", "remove", "--force", scratch],
                check=False, capture_output=True, text=True,
            )

    print(f"fix rationale: {fix.rationale}")
    print(f"fix blast_radius: {fix.blast_radius}")

    OUT_DIR.mkdir(exist_ok=True)
    diff_path = OUT_DIR / f"{seed}-fix.diff"
    diff_path.write_text(fix.diff)
    print(f"wrote {diff_path}")

    scope_result = validate_diff(fix.diff, fix.lockfile_change_reason)
    print(f"scope guard: rejected={scope_result.rejected} reasons={scope_result.reasons}")

    anticheat_result = check_diff(fix.diff)
    print(
        f"anticheat guard: rejected={anticheat_result.rejected} "
        f"reject_reasons={anticheat_result.reject_reasons} "
        f"requires_human_review={anticheat_result.requires_human_review} "
        f"review_reasons={anticheat_result.review_reasons}"
    )

    if scope_result.rejected or anticheat_result.rejected:
        sys.exit(1)


if __name__ == "__main__":
    main()
