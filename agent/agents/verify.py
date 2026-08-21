"""Verification: deterministic Docker-based test execution + result diffing
(DECISIONS.md #21 -- not LLM-backed, even though the spec's tier table
allows a small model for summarization). Two `docker run`s against the
SAME pre-built image (DECISIONS.md #15) -- one baseline (no patch mounted),
one with the candidate diff mounted as /workspace/patch.diff -- never a
docker build per verification attempt.
"""

import json
import subprocess
import tempfile
from pathlib import Path

from agent.llm.schema import TestRunSummary, VerificationResult
from agent.trace import TraceEvent, inputs_hash, now, record_trace

REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFY_IMAGE = "agentic-fixer-verify:base"

_image_built = False


def _ensure_image_built() -> None:
    global _image_built
    if _image_built:
        return
    subprocess.run(
        ["docker", "build", "-f", "verify/Dockerfile", "-t", VERIFY_IMAGE, "."],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    _image_built = True


def _run_container(checkout_path: Path, patch_path: Path | None) -> dict:
    with tempfile.TemporaryDirectory(prefix="verify-out-") as out_dir:
        args = [
            "docker", "run", "--rm",
            "-v", f"{checkout_path}:/workspace/src:ro",
            "-v", f"{out_dir}:/workspace/out",
        ]
        if patch_path is not None:
            args += ["-v", f"{patch_path}:/workspace/patch.diff:ro"]
        args.append(VERIFY_IMAGE)
        subprocess.run(args, check=True, capture_output=True, text=True)
        return json.loads((Path(out_dir) / "results.json").read_text())


def _summarize(raw: dict) -> TestRunSummary:
    tests = raw.get("tests", {})
    return TestRunSummary(
        passed_tests=sorted(name for name, status in tests.items() if status == "passed"),
        failed_tests=sorted(name for name, status in tests.items() if status == "failed"),
    )


def run_verification(pre_fix_checkout: Path, diff_text: str) -> VerificationResult:
    _ensure_image_built()

    baseline_raw = _run_container(pre_fix_checkout, None)
    baseline = _summarize(baseline_raw)

    with tempfile.NamedTemporaryFile("w", suffix=".diff", delete=False) as f:
        f.write(diff_text)
        patch_path = Path(f.name)
    try:
        patched_raw = _run_container(pre_fix_checkout, patch_path)
    finally:
        patch_path.unlink(missing_ok=True)
    patched = _summarize(patched_raw)

    patch_applied = patched_raw.get("patch_applied", True)
    regressions = sorted(set(baseline.passed_tests) & set(patched.failed_tests))
    newly_passing = sorted(set(baseline.failed_tests) & set(patched.passed_tests))
    passed = patch_applied and len(patched.failed_tests) == 0

    if not patch_applied:
        delta = "patch failed to apply"
    else:
        delta = (
            f"{len(baseline.failed_tests)} failed -> {len(patched.failed_tests)} failed, "
            f"{len(baseline.passed_tests)} passed -> {len(patched.passed_tests)} passed"
        )

    result = VerificationResult(
        baseline_summary=baseline,
        patched_summary=patched,
        delta=delta,
        passed=passed,
        regressions=regressions,
        newly_passing=newly_passing,
    )

    record_trace(TraceEvent(
        timestamp=now(),
        actor="verify",
        decision=f"verification {'passed' if passed else 'failed'}: {delta}",
        reasoning=(
            f"patch_applied={patch_applied}, regressions={regressions}, "
            f"remaining_failures={patched.failed_tests}"
        ),
        evidence=[delta],
        alternatives_rejected=(
            [f"regression introduced in {t!r}" for t in regressions]
            if regressions else []
        ),
        inputs_hash=inputs_hash({"diff": diff_text, "checkout": str(pre_fix_checkout)}),
    ))
    return result
