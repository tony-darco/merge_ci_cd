#!/usr/bin/env python3
"""Build a seed's image, import it into k3d, and submit the sample pipeline.

Usage: uv run scripts/submit_pipeline.py --seed <name>

Seed names map to sample-app branches as seed/<name> (e.g. --seed code-defect
checks out sample-app's seed/code-defect branch). commit-sha and
changed-files are computed host-side (where git actually lives, not inside
the cluster) and printed for scripts/capture_fixture.py to reuse.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_APP_DIR = REPO_ROOT / "sample-app"
PIPELINE_MANIFEST = REPO_ROOT / "manifests" / "sample-pipeline.yaml"
CLUSTER_NAME = "agentic-fixer"
BASE_BRANCH = "main"

# seeds that need the low-memory template (resource quantities can't be
# parameterized via {{workflow.parameters...}}, see LOG.md -- so this picks
# an --entrypoint instead)
ENTRYPOINT_OVERRIDES = {"infra-failure": "test-oom-limited"}


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print(f"$ {' '.join(cmd)}", file=sys.stderr)
    return subprocess.run(cmd, check=True, **kwargs)


def git(*args: str, capture: bool = False) -> str | None:
    cmd = ["git", "-C", str(SAMPLE_APP_DIR), *args]
    if capture:
        result = run(cmd, capture_output=True, text=True)
        return result.stdout.strip()
    run(cmd)
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", required=True, help="e.g. code-defect, infra-failure")
    args = parser.parse_args()
    seed = args.seed
    branch = f"seed/{seed}"
    image = f"sample-app:{seed}"
    entrypoint = ENTRYPOINT_OVERRIDES.get(seed, "test")

    git("checkout", branch)
    commit_sha = git("rev-parse", "HEAD", capture=True)
    changed_files_raw = git("diff", "--name-only", f"{BASE_BRANCH}...{branch}", capture=True)
    changed_files = [f for f in changed_files_raw.splitlines() if f] if changed_files_raw else []
    print(f"commit_sha={commit_sha}", file=sys.stderr)
    print(f"changed_files={json.dumps(changed_files)}", file=sys.stderr)

    run(["docker", "build", "-t", image, str(SAMPLE_APP_DIR)])
    run(["k3d", "image", "import", image, "-c", CLUSTER_NAME])

    # `argo submit --wait -o json` prints the pre-completion object (see
    # LOG.md), and exits non-zero whenever the *workflow* fails -- expected
    # for these deliberately-broken seeds, not a script error. So: submit
    # (get the name), wait (block for a terminal phase), get (real status).
    name = run(
        ["argo", "submit", "-n", "argo", str(PIPELINE_MANIFEST), "--entrypoint", entrypoint,
         "--parameter", f"image={image}", "-o", "name"],
        capture_output=True, text=True,
    ).stdout.strip()
    subprocess.run(["argo", "wait", "-n", "argo", name], check=False)
    workflow = json.loads(
        run(["argo", "get", "-n", "argo", name, "-o", "json"], capture_output=True, text=True).stdout
    )
    phase = workflow["status"]["phase"]
    print(f"workflow_name={name}")
    print(f"phase={phase}", file=sys.stderr)


if __name__ == "__main__":
    main()
