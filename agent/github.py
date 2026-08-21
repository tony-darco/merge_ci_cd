"""M6: push the verified fix and open a pull request for human review.

The PR body is assembled from the run's own recorded TraceEvents rather
than from a separately-written summary. That is deliberate: if the PR needs
something the trace does not contain, the gap belongs in the trace, not in
a parallel narrative that can drift from what the agents actually decided.

Nothing here auto-merges. Every PR carries an explicit disclaimer and lands
open for review (DECISIONS.md #6).
"""

import os
import subprocess
import tempfile
from pathlib import Path

from agent.llm.schema import DiagnosisResult, FailureContext, FixResult, VerificationResult
from agent.trace import TraceEvent, inputs_hash, now, record_trace

SAMPLE_APP_REPO = os.environ.get("SAMPLE_APP_REPO", "tony-darco/sample-app")
# The branch a PR targets must be the one that actually failed, not the
# project default. Basing on `main` produced a PR whose diff was the
# difference between the fixed seed and a branch that never had the bug --
# it rendered as a pointless refactor rather than the one-line fix (see
# LOG.md). Only used as a fallback when the caller cannot say.
DEFAULT_BASE_BRANCH = os.environ.get("SAMPLE_APP_BASE_BRANCH", "main")

# Never omitted, never softened, and not conditional on the confidence tier
# -- the whole point of decision #6 is that a human decides, and the person
# reading the PR is the one who needs to be told.
DISCLAIMER = (
    "> **This fix was generated and verified by an automated agent.** It has not been "
    "reviewed by a human. \"Verified\" means the project's own test suite passed against "
    "this exact diff -- see the Verification section below for where that ran -- and does "
    "not mean the change is correct, idiomatic, or appropriate. Review it as you would any "
    "untrusted patch before merging."
)

_CONFIDENCE_CAVEATS = {
    "HIGH": (
        "Every signal available lined up: the suite passed with no regressions, diagnosis "
        "settled on a single hypothesis, and the fix was small and landed on the first attempt. "
        "This is the strongest evidence this system can produce, which is still not a substitute "
        "for review."
    ),
    "MEDIUM": (
        "Verification passed, but at least one signal was weaker than ideal -- a competing "
        "hypothesis was considered, more than one attempt was needed, or the diff is larger "
        "than a typical targeted fix. Read this one closely."
    ),
    "LOW": (
        "Verification did not pass cleanly. This change should not be merged on the strength "
        "of anything in this description."
    ),
}


def _verification_environment_note() -> str:
    """Describe the environment the tests actually ran in.

    Deliberately not a fixed "run in an isolated sandbox" sentence: that is
    true of the Argo verifier and false of the local Docker one, and a PR
    body that overstates its own isolation guarantees is worse than one
    that says nothing. Even the sandbox claim is qualified -- the egress
    policy is enforced by a controller that syncs shortly after a pod
    starts, so a short-lived pod can briefly outrun it (see LOG.md).
    """
    from agent.config import VERIFIER

    if VERIFIER == "argo":
        return (
            "Ran against this exact diff in a dedicated Kubernetes sandbox namespace with a "
            "default-deny egress NetworkPolicy (DNS, artifact store, and API server only). "
            "Note the policy is applied by the CNI shortly after pod start, so a very "
            "short-lived pod may briefly predate enforcement."
        )
    return (
        "Ran against this exact diff in a local Docker container. **This environment is not "
        "network-isolated** — it is the development verifier, not the sandboxed one."
    )


def _git(checkout_path: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-C", str(checkout_path), *args], check=check, capture_output=True, text=True
    )
    return result.stdout.strip()


def branch_name_for(context: FailureContext) -> str:
    short_sha = (context.commit_sha or "unknown")[:8]
    return f"agentic-fix/{context.workflow_name}-{short_sha}"


def push_fix_branch(checkout_path: Path, context: FailureContext, diff_text: str) -> str:
    """Apply the verified diff on a new branch and push it.

    Runs inside the same checkout the graph already used, so what gets
    pushed is exactly what was verified -- not a re-derivation of it.
    """
    branch = branch_name_for(context)
    _git(checkout_path, "checkout", "-B", branch)

    with tempfile.NamedTemporaryFile("w", suffix=".diff", delete=False) as f:
        f.write(diff_text)
        patch_path = Path(f.name)
    try:
        _git(checkout_path, "apply", str(patch_path))
    finally:
        patch_path.unlink(missing_ok=True)

    _git(checkout_path, "add", "-A")
    _git(
        checkout_path,
        "-c", "user.email=agentic-fixer@local",
        "-c", "user.name=Agentic CI/CD Fixer",
        "commit", "-m", f"Fix CI failure in {context.workflow_name}",
    )
    _git(checkout_path, "push", "--force", "origin", branch)
    return branch


def build_pr_body(
    context: FailureContext,
    diagnosis: DiagnosisResult,
    fix: FixResult,
    verification: VerificationResult,
    confidence: str,
    trace_events: list[TraceEvent],
) -> str:
    v = verification
    total = len(v.patched_summary.passed_tests) + len(v.patched_summary.failed_tests)

    evidence_block = "\n".join(f"> `{e.excerpt.strip()}`" for e in diagnosis.evidence) or "> _(none cited)_"

    alternative = (
        f"The agent also considered: {diagnosis.alternative_hypothesis}"
        if diagnosis.alternative_hypothesis.strip()
        else "No competing hypothesis was considered — the evidence pointed one way."
    )

    trace_rows = "\n".join(
        f"| {e.actor} | {e.decision} | {e.model or '_deterministic_'} |" for e in trace_events
    ) or "| _(no events recorded)_ | | |"

    newly_passing = "\n".join(f"- `{t}`" for t in v.newly_passing) or "- _(none)_"
    regressions = "\n".join(f"- `{t}`" for t in v.regressions) or "- _(none)_"

    return f"""{DISCLAIMER}

## What failed

Workflow `{context.workflow_name}` failed at commit `{context.commit_sha[:8] if context.commit_sha else "unknown"}`.

## Root cause

{diagnosis.root_cause}

**Evidence cited from the failure log:**

{evidence_block}

{alternative}

## The fix

{fix.rationale}

**Blast radius (agent's own description):** {fix.blast_radius}

## Verification

{_verification_environment_note()}

- **Result:** {v.delta}
- **Now passing:** {len(v.patched_summary.passed_tests)}/{total}

**Newly passing:**
{newly_passing}

**Regressions:**
{regressions}

## Confidence: {confidence}

{_CONFIDENCE_CAVEATS.get(confidence, "No caveat available for this tier.")}

Confidence is computed from observed signals — verification outcome, diagnosis
ambiguity, diff size, attempt count. It is never self-reported by a model.

## Decision trace

Every decision the agents made during this run, in order:

| Actor | Decision | Model |
|---|---|---|
{trace_rows}
"""


def open_pr(
    branch: str, title: str, body: str, repo: str = SAMPLE_APP_REPO, base: str | None = None
) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(body)
        body_path = Path(f.name)
    try:
        result = subprocess.run(
            [
                "gh", "pr", "create",
                "--repo", repo,
                "--title", title,
                "--body-file", str(body_path),
                "--base", base or DEFAULT_BASE_BRANCH,
                "--head", branch,
            ],
            check=True, capture_output=True, text=True,
        )
    finally:
        body_path.unlink(missing_ok=True)
    return result.stdout.strip().splitlines()[-1]


def create_pull_request(
    checkout_path: Path,
    context: FailureContext,
    diagnosis: DiagnosisResult,
    fix: FixResult,
    verification: VerificationResult,
    confidence: str,
    trace_events: list[TraceEvent],
    base_branch: str | None = None,
) -> str:
    branch = push_fix_branch(checkout_path, context, fix.diff)
    title = f"[agentic-fixer] {diagnosis.root_cause[:60]}"
    body = build_pr_body(context, diagnosis, fix, verification, confidence, trace_events)
    url = open_pr(branch, title, body, base=base_branch)

    record_trace(TraceEvent(
        timestamp=now(),
        actor="github",
        decision=f"opened pull request {url}",
        reasoning=(
            f"verification passed with {len(verification.regressions)} regressions and confidence "
            f"{confidence}; opening for human review rather than merging (DECISIONS.md #6)"
        ),
        evidence=[verification.delta],
        inputs_hash=inputs_hash({"branch": branch, "diff": fix.diff}),
    ))
    return url
