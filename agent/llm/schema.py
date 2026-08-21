from typing import Literal

from pydantic import BaseModel

TriageCategory = Literal[
    "CODE_DEFECT",
    "DEPENDENCY_ISSUE",
    "INFRA_FAILURE",
    "FLAKY",
    "CONFIG_OR_SECRET",
    "UNKNOWN",
]

# Only these proceed to Diagnosis/Fix (spec §5.1). Everything else exits
# with a diagnosis comment and no fix attempt.
FIXABLE_CATEGORIES: frozenset[TriageCategory] = frozenset({"CODE_DEFECT", "DEPENDENCY_ISSUE"})


class FailedNode(BaseModel):
    name: str
    display_name: str
    message: str
    template_name: str
    phase: str
    pod_name: str
    finished_at: str | None = None


class FailureContext(BaseModel):
    """The contract between the cluster and the agents (see DECISIONS.md #13).

    M0 captures/hand-authors one of these per seed under fixtures/<seed>/context.json.
    M1-M4 read only from those fixtures. M5's exit handler produces this same shape live.
    """

    workflow_name: str
    workflow_namespace: str
    failed_nodes: list[FailedNode]
    logs: dict[str, str]
    commit_sha: str
    changed_files: list[str]
    timestamp: str


class TriageResult(BaseModel):
    category: TriageCategory
    reasoning: str
    evidence_summary: str


class EvidenceCitation(BaseModel):
    source: str
    excerpt: str
    line_range: str | None = None


class DiagnosisResult(BaseModel):
    root_cause: str
    evidence: list[EvidenceCitation]
    alternative_hypothesis: str
    affected_files: list[str]
    category: str


class ProposedFileChange(BaseModel):
    path: str
    new_content: str


class FixProposal(BaseModel):
    """What the Fix LLM actually produces: full replacement content per
    touched file, not hand-written diff syntax. Asking a local model to
    emit correctly-formatted unified-diff hunks (line numbers, @@ markers)
    is a known reliability trap -- schema validation only checks that
    `diff` is a string, so a syntactically broken diff would pass
    validation and only fail later at `git apply`. Rewriting a file's full
    content is a much easier task, and fix.py computes a guaranteed-valid
    unified diff from it via difflib.
    """

    changed_files: list[ProposedFileChange]
    rationale: str
    blast_radius: str
    lockfile_change_reason: str | None = None


class FixResult(BaseModel):
    """What the rest of the system (scope guard, anticheat guard, verify)
    actually consumes -- a real unified diff, computed by fix.py from a
    FixProposal, never generated directly by the LLM.
    """

    diff: str
    rationale: str
    blast_radius: str
    lockfile_change_reason: str | None = None


class AntiCheatResult(BaseModel):
    rejected: bool
    reject_reasons: list[str]
    requires_human_review: bool
    review_reasons: list[str]
