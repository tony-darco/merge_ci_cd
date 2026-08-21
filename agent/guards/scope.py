"""Path allowlist and diff-scope enforcement (spec §5.3, §7.3). Hard
constraints enforced IN CODE, not in the prompt: a Fix Agent output that
violates these is rejected here, not merely discouraged in the prompt text.
"""

import re

from pydantic import BaseModel
from unidiff import PatchSet

ALLOWED_PREFIXES = ("src/", "tests/")
MAX_CHANGED_LINES = 150
BLOCKED_PATH_PATTERNS = [
    re.compile(r"^manifests/"),
    re.compile(r"^\.github/"),
    re.compile(r"\.ya?ml$"),
    re.compile(r"(?i)secret"),
    re.compile(r"(?i)credential"),
    re.compile(r"^\.env"),
    re.compile(r"(?i)iam"),
    re.compile(r"(?i)policy\.json$"),
]
LOCKFILE_PATTERNS = [
    re.compile(r"^requirements.*\.txt$"),
    re.compile(r"^uv\.lock$"),
    re.compile(r"^poetry\.lock$"),
    re.compile(r"^package-lock\.json$"),
]
# Defense in depth: the Fix Agent's checkout is always a sample-app-only
# clone (DECISIONS.md #10), so agent source is never actually present on
# disk to touch -- this check is a belt-and-suspenders path guard, not the
# primary mechanism.
AGENT_SOURCE_PATTERNS = [re.compile(r"^agent/"), re.compile(r"^scripts/")]


class ScopeCheckResult(BaseModel):
    rejected: bool
    reasons: list[str]


def _touched_paths(patch: PatchSet) -> list[str]:
    paths = set()
    for patched_file in patch:
        for p in (patched_file.source_file, patched_file.target_file):
            if p and p not in ("/dev/null",):
                # unidiff keeps the a/ b/ prefixes from the diff headers
                paths.add(re.sub(r"^[ab]/", "", p))
    return sorted(paths)


def validate_diff(diff_text: str, lockfile_change_reason: str | None = None) -> ScopeCheckResult:
    reasons: list[str] = []
    try:
        patch = PatchSet(diff_text)
    except Exception as e:
        return ScopeCheckResult(rejected=True, reasons=[f"could not parse diff: {e}"])

    if len(patch) == 0:
        return ScopeCheckResult(rejected=True, reasons=["diff contains no file changes"])

    paths = _touched_paths(patch)

    for path in paths:
        is_lockfile = any(pattern.search(path) for pattern in LOCKFILE_PATTERNS)
        if is_lockfile:
            # Lockfiles typically sit at the repo root, outside src/tests --
            # a valid reason substitutes for the allowlist check, it doesn't
            # need to also satisfy it.
            if not (lockfile_change_reason and lockfile_change_reason.strip()):
                reasons.append(f"{path!r} is a lockfile change with no lockfile_change_reason given")
        elif not path.startswith(ALLOWED_PREFIXES):
            reasons.append(f"{path!r} is outside the allowlisted paths ({ALLOWED_PREFIXES})")

        for pattern in BLOCKED_PATH_PATTERNS:
            if pattern.search(path):
                reasons.append(f"{path!r} matches a blocked pattern ({pattern.pattern!r} -- CI config/secret/IAM)")
        for pattern in AGENT_SOURCE_PATTERNS:
            if pattern.search(path):
                reasons.append(f"{path!r} touches the agent's own source, which is never permitted")

    total_changed_lines = sum(f.added + f.removed for f in patch)
    if total_changed_lines > MAX_CHANGED_LINES:
        reasons.append(f"diff changes {total_changed_lines} lines, exceeding the {MAX_CHANGED_LINES}-line budget")

    return ScopeCheckResult(rejected=len(reasons) > 0, reasons=reasons)
