"""M5 exit-handler entrypoint: assemble a FailureContext from a live
workflow and hand it to the same graph the fixture-driven CLI runs.

Deliberately thin. The fixtures captured at M0 froze the payload shape
(DECISIONS.md #13) precisely so this step would be an adapter rather than
a second implementation -- everything downstream is unchanged.

Two things differ from scripts/capture_fixture.py, which does the same job
on a developer's laptop:
  - Workflow status comes from `kubectl`, not the `argo` CLI, so the agent
    image needs no extra binary and doesn't depend on argo-server being
    reachable from inside a pod (DECISIONS.md #26).
  - commit_sha/changed_files are read from the workflow's own parameters
    rather than a host git checkout, which the exit-handler pod has no
    access to.

The source checkout itself is NOT fetched here -- it arrives on disk as the
`fetch-source` DAG step's artifact, already at the right commit
(DECISIONS.md #29).
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from agent.llm.schema import FailureContext
from agent.orchestrator import describe_outcome, run_graph_for_checkout

FAILED_PHASES = {"Failed", "Error"}


def _kubectl(args: list[str]) -> str:
    result = subprocess.run(["kubectl", *args], check=True, capture_output=True, text=True)
    return result.stdout


def _pod_logs(pod_name: str, namespace: str) -> str:
    result = subprocess.run(
        ["kubectl", "logs", pod_name, "-n", namespace, "-c", "main"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # An OOMKilled pod often has no readable log at all -- the real
        # signal lives in the node's message field (DECISIONS.md #22).
        print(f"warning: kubectl logs failed for {pod_name}: {result.stderr.strip()}", file=sys.stderr)
        return ""
    return result.stdout


def _workflow_parameters(workflow: dict) -> dict[str, str]:
    params = workflow.get("spec", {}).get("arguments", {}).get("parameters", [])
    return {p["name"]: p.get("value", "") for p in params}


def build_context(workflow_name: str, namespace: str) -> FailureContext:
    raw = _kubectl(["get", "workflow", workflow_name, "-n", namespace, "-o", "json"])
    workflow = json.loads(raw)

    failed_nodes = []
    logs: dict[str, str] = {}
    for node in workflow.get("status", {}).get("nodes", {}).values():
        if node.get("type") != "Pod" or node.get("phase") not in FAILED_PHASES:
            continue
        pod_name = node.get("id", node.get("name", ""))
        failed_nodes.append({
            "name": node.get("name", ""),
            "display_name": node.get("displayName", ""),
            "message": node.get("message", ""),
            "template_name": node.get("templateName", ""),
            "phase": node.get("phase", ""),
            "pod_name": pod_name,
            "finished_at": node.get("finishedAt"),
        })
        logs[node.get("name", pod_name)] = _pod_logs(pod_name, namespace)

    params = _workflow_parameters(workflow)
    changed_files = [f for f in params.get("changed-files", "").split(",") if f]

    return FailureContext(
        workflow_name=workflow["metadata"]["name"],
        workflow_namespace=workflow["metadata"]["namespace"],
        failed_nodes=failed_nodes,
        logs=logs,
        commit_sha=params.get("commit-sha", ""),
        changed_files=changed_files,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow-name", required=True)
    parser.add_argument("--namespace", default="argo")
    parser.add_argument(
        "--checkout-path",
        default=os.environ.get("SOURCE_CHECKOUT_PATH", "/workspace/src"),
        help="source tree supplied by the fetch-source DAG step",
    )
    parser.add_argument("--open-pr", action="store_true")
    args = parser.parse_args()

    context = build_context(args.workflow_name, args.namespace)
    if not context.failed_nodes:
        print("no failed nodes found -- nothing to diagnose")
        return

    from agent.llm.providers.ollama import OllamaProvider

    final_state = run_graph_for_checkout(
        context, Path(args.checkout_path), OllamaProvider(), open_pr=args.open_pr
    )
    print(describe_outcome(final_state))


if __name__ == "__main__":
    main()
