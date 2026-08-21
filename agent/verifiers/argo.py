"""Argo verification backend (DECISIONS.md #28): submits the same
agentic-fixer-verify:base image as a real Workflow into a locked-down
sandbox namespace, rather than running Docker itself. Nothing here needs
privileged access, a Docker socket, or minio credentials.

The source tarball was already uploaded to the in-cluster artifact store by
the `fetch-source` step that ran BEFORE this code (DECISIONS.md #29) -- a
node cannot read back its own not-yet-uploaded output artifact, which is
why the exit hook is a two-step DAG. This reads that completed step's
artifact key and passes it to each verify submission.
"""

import json
import os
import subprocess
import time
from pathlib import Path

from agent.config import SANDBOX_NAMESPACE, VERIFY_WORKFLOW_TEMPLATE
from agent.verifiers.base import Verifier

POLL_INTERVAL_SECONDS = 3
POLL_TIMEOUT_SECONDS = 600
_TERMINAL_PHASES = {"Succeeded", "Failed", "Error"}


def _kubectl_json(args: list[str]) -> dict:
    result = subprocess.run(
        ["kubectl", *args, "-o", "json"], check=True, capture_output=True, text=True
    )
    return json.loads(result.stdout)


class ArgoVerifier(Verifier):
    name = "argo"

    def __init__(self, hook_workflow: str | None = None, namespace: str | None = None) -> None:
        # Set from {{workflow.name}} by the exit-hook template.
        self.hook_workflow = hook_workflow or os.environ["HOOK_WORKFLOW_NAME"]
        self.hook_namespace = namespace or os.environ.get("HOOK_NAMESPACE", "argo")
        self._source_key: str | None = None

    def _fetch_source_artifact_key(self) -> str:
        """Read the s3 key of the `fetch-source` step's output artifact from
        this hook workflow's own status. Safe to read because that step has
        completed -- see DECISIONS.md #29 for why the single-step version
        of this deadlocks.
        """
        if self._source_key is not None:
            return self._source_key
        workflow = _kubectl_json(
            ["get", "workflow", self.hook_workflow, "-n", self.hook_namespace]
        )
        for node in workflow.get("status", {}).get("nodes", {}).values():
            if "fetch-source" not in node.get("displayName", ""):
                continue
            for artifact in node.get("outputs", {}).get("artifacts", []):
                key = artifact.get("s3", {}).get("key")
                if key:
                    self._source_key = key
                    return key
        raise RuntimeError(
            f"no fetch-source output artifact found on workflow {self.hook_workflow!r} -- "
            "the exit hook's first DAG step must have completed and uploaded the source tarball"
        )

    def _submit(self, diff_text: str | None) -> str:
        args = [
            "argo", "submit",
            "--from", f"workflowtemplate/{VERIFY_WORKFLOW_TEMPLATE}",
            "-n", SANDBOX_NAMESPACE,
            "--parameter", f"source-key={self._fetch_source_artifact_key()}",
            "--parameter", f"patch-diff={diff_text or ''}",
            "-o", "name",
        ]
        result = subprocess.run(args, check=True, capture_output=True, text=True)
        return result.stdout.strip()

    def _wait(self, name: str) -> dict:
        deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            workflow = _kubectl_json(["get", "workflow", name, "-n", SANDBOX_NAMESPACE])
            if workflow.get("status", {}).get("phase") in _TERMINAL_PHASES:
                return workflow
            time.sleep(POLL_INTERVAL_SECONDS)
        raise TimeoutError(f"verify workflow {name!r} did not finish within {POLL_TIMEOUT_SECONDS}s")

    def _run_suite(self, checkout_path: Path, diff_text: str | None) -> dict:
        workflow = self._wait(self._submit(diff_text))
        for node in workflow.get("status", {}).get("nodes", {}).values():
            for param in node.get("outputs", {}).get("parameters", []):
                if param.get("name") == "results":
                    return json.loads(param["value"])
        # The suite never produced a result -- an infra failure of the
        # verification itself, not a test outcome. Reported as "patch didn't
        # apply" so the caller sees a real, parseable verdict rather than a
        # crash, matching how verify/entrypoint.sh handles the same case.
        return {"tests": {}, "patch_applied": False}
