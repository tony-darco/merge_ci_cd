#!/usr/bin/env python3
"""Capture a real cluster run's failure context as a fixture.

Usage: uv run scripts/capture_fixture.py --seed <name> --workflow-name <name>

Writes fixtures/<seed>/context.json, matching agent.llm.schema.FailureContext.
Logs are stored raw/unredacted — redaction is a downstream M1 processing
step, tested against these fixtures, not something capture does itself.

Reads each failed node's `message` field from `argo get -o json`, not only
pod stdout: an OOMKilled pod's `kubectl logs` output is frequently empty
(the process is killed before it can flush), so the real signal for that
case lives in node status, not log text (see DECISIONS.md #22).
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_APP_DIR = REPO_ROOT / "sample-app"
FIXTURES_DIR = REPO_ROOT / "fixtures"
BASE_BRANCH = "main"
FAILED_PHASES = {"Failed", "Error"}


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(SAMPLE_APP_DIR), *args], check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def kubectl_logs(pod_name: str, namespace: str = "argo") -> str:
    result = subprocess.run(
        ["kubectl", "logs", pod_name, "-n", namespace, "-c", "main"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"warning: kubectl logs failed for pod {pod_name}: {result.stderr.strip()}", file=sys.stderr)
        return ""
    return result.stdout


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", required=True)
    parser.add_argument("--workflow-name", required=True)
    parser.add_argument("--namespace", default="argo")
    args = parser.parse_args()

    result = subprocess.run(
        ["argo", "get", "-n", args.namespace, args.workflow_name, "-o", "json"],
        check=True,
        capture_output=True,
        text=True,
    )
    workflow = json.loads(result.stdout)
    nodes = workflow.get("status", {}).get("nodes", {})

    failed_nodes = []
    logs = {}
    for node in nodes.values():
        if node.get("type") != "Pod" or node.get("phase") not in FAILED_PHASES:
            continue
        pod_name = node.get("id", node.get("name", ""))
        failed_nodes.append(
            {
                "name": node.get("name", ""),
                "display_name": node.get("displayName", ""),
                "message": node.get("message", ""),
                "template_name": node.get("templateName", ""),
                "phase": node.get("phase", ""),
                "pod_name": pod_name,
                "finished_at": node.get("finishedAt"),
            }
        )
        logs[node.get("name", pod_name)] = kubectl_logs(pod_name, args.namespace)

    if not failed_nodes:
        print("warning: no failed Pod nodes found in workflow status", file=sys.stderr)

    branch = f"seed/{args.seed}"
    commit_sha = git("rev-parse", branch)
    changed_files_raw = git("diff", "--name-only", f"{BASE_BRANCH}...{branch}")
    changed_files = [f for f in changed_files_raw.splitlines() if f]

    context = {
        "workflow_name": workflow["metadata"]["name"],
        "workflow_namespace": workflow["metadata"]["namespace"],
        "failed_nodes": failed_nodes,
        "logs": logs,
        "commit_sha": commit_sha,
        "changed_files": changed_files,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    out_dir = FIXTURES_DIR / args.seed
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "context.json"
    out_path.write_text(json.dumps(context, indent=2) + "\n")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
