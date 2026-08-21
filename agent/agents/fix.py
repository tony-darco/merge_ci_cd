"""Fix: minimal diff + rationale + self-declared blast radius (spec §5.3).
Reads only retrieved, relevant source files -- never a whole-repo dump.
"""

import difflib
import re
from pathlib import Path

from agent.config import FIX_MODEL
from agent.llm.interface import LLMProvider
from agent.llm.schema import DiagnosisResult, FailureContext, FixProposal, FixResult
from agent.trace import TraceEvent, inputs_hash, now, record_trace

_FAILED_TEST_PATTERN = re.compile(r"^FAILED (\S+\.py)::", re.MULTILINE)
_IMPORT_PATTERN = re.compile(r"^from (\w+)\.(\w+) import", re.MULTILINE)
_PATH_ANCHORS = ("src/", "tests/")


def _normalize_path(path: str) -> str:
    """Diagnosis's affected_files isn't guaranteed to come back relative to
    the repo root (see LOG.md) -- a local model may return an absolute path
    (its own checkout, or a container's /app/... layout) despite the prompt
    asking otherwise. Anchor on a known root-level directory instead of
    trusting the string as-is.
    """
    normalized = path.replace("\\", "/")
    for anchor in _PATH_ANCHORS:
        idx = normalized.find(anchor)
        if idx != -1:
            return normalized[idx:]
    return normalized.lstrip("/")


def _extract_failing_test_files(logs: dict[str, str]) -> list[str]:
    files: list[str] = []
    for log in logs.values():
        for match in _FAILED_TEST_PATTERN.finditer(log):
            path = _normalize_path(match.group(1))
            if path not in files:
                files.append(path)
    return files


def _infer_source_files_from_test_imports(checkout_path: Path, test_file_paths: list[str]) -> list[str]:
    """Don't trust affected_files alone (see LOG.md -- Diagnosis has named
    the test file instead of the source file it detects). Follow the
    failing test's own imports to the source it's actually testing.
    """
    inferred: list[str] = []
    for test_path in test_file_paths:
        full_path = checkout_path / test_path
        if not full_path.is_file():
            continue
        for package, module in _IMPORT_PATTERN.findall(full_path.read_text()):
            candidate = f"src/{package}/{module}.py"
            if (checkout_path / candidate).is_file() and candidate not in inferred:
                inferred.append(candidate)
    return inferred


def _read_relevant_files(checkout_path: Path, diagnosis: DiagnosisResult, context: FailureContext) -> dict[str, str]:
    normalized_affected = [_normalize_path(p) for p in diagnosis.affected_files]
    failing_tests = _extract_failing_test_files(context.logs)
    inferred_sources = _infer_source_files_from_test_imports(checkout_path, failing_tests)
    paths = list(dict.fromkeys(normalized_affected + failing_tests + inferred_sources))
    contents = {}
    for rel_path in paths:
        full_path = checkout_path / rel_path
        if full_path.is_file():
            contents[rel_path] = full_path.read_text()
    return contents


def _unified_diff_for(path: str, old_content: str, new_content: str) -> str:
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    diff_lines = difflib.unified_diff(old_lines, new_lines, fromfile=f"a/{path}", tofile=f"b/{path}")
    return "".join(diff_lines)


def run_fix(
    diagnosis: DiagnosisResult, context: FailureContext, checkout_path: Path, provider: LLMProvider
) -> FixResult:
    files = _read_relevant_files(checkout_path, diagnosis, context)
    prompt = _build_prompt(diagnosis, files)
    proposal, meta = provider.generate_structured(FIX_MODEL, prompt, FixProposal)

    diff_parts = []
    skipped: list[str] = []
    for change in proposal.changed_files:
        path = _normalize_path(change.path)
        if path not in files:
            # The model was never shown this file's real content -- treating
            # its guess as an authoritative rewrite would silently produce a
            # diff that claims to *create* a file that already exists on
            # disk (see LOG.md). Refuse rather than emit a fictional diff.
            skipped.append(path)
            continue
        diff = _unified_diff_for(path, files[path], change.new_content)
        if diff:
            diff_parts.append(diff)
    result = FixResult(
        diff="".join(diff_parts),
        rationale=proposal.rationale,
        blast_radius=proposal.blast_radius,
        lockfile_change_reason=proposal.lockfile_change_reason,
    )

    record_trace(TraceEvent(
        timestamp=now(),
        actor="fix",
        decision=f"proposed fix touching {[c.path for c in proposal.changed_files]}, blast radius: {result.blast_radius}",
        reasoning=result.rationale,
        evidence=[diagnosis.root_cause],
        alternatives_rejected=(
            [f"skipped proposed change to {p!r} -- model was never shown this file's real content" for p in skipped]
        ),
        inputs_hash=inputs_hash({"root_cause": diagnosis.root_cause, "files": sorted(files)}),
        model=FIX_MODEL,
        provider=meta.get("provider"),
        tokens=meta.get("tokens"),
        latency=meta.get("latency"),
    ))
    return result


def _build_prompt(diagnosis: DiagnosisResult, files: dict[str, str]) -> str:
    file_blocks = "\n\n".join(
        f"--- {path} ---\n<file_content>\n{content}\n</file_content>" for path, content in files.items()
    )
    return f"""You are a fix agent for a CI failure. Given the diagnosed root cause and the relevant source files, produce a minimal fix.

Root cause: {diagnosis.root_cause}
Evidence: {[e.excerpt for e in diagnosis.evidence]}

Constraints:
- Only touch files under src/ or tests/.
- Keep the fix minimal -- do not refactor or reformat unrelated code, and do not touch files that aren't part of the root cause.
- Never delete or skip a failing test, and never weaken an assertion, to make it pass.
- For each file you change, return its COMPLETE new content (not a diff, not a snippet) -- the full file, with your fix applied.

{file_blocks}

Return JSON matching this schema exactly:
{{"changed_files": [{{"path": "<file path exactly as shown above>", "new_content": "<the file's full new content>"}}], "rationale": "<plain-English explanation of the fix>", "blast_radius": "<short description of files/lines touched>", "lockfile_change_reason": null}}
"""
