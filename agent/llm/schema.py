from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints

# Reasoning is mandatory, and enforcing it *here* rather than only at the
# trace boundary is deliberate. agent/trace.py raises on empty reasoning --
# a decision with no reasoning is a bug, not a logging gap -- but a model
# that returns "" would then crash the run at record_trace time, well after
# the point where anything could be done about it. Constraining the field
# instead routes it into generate_structured's existing retry-with-feedback
# loop, so the model is told to explain itself and asked again. Observed
# live: qwen3.5:0.8b intermittently returns an empty reasoning string
# (LOG.md).
Reasoning = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

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
    reasoning: Reasoning
    evidence_summary: str


class EvidenceCitation(BaseModel):
    source: str
    excerpt: str
    line_range: str | None = None


class DiagnosisResult(BaseModel):
    root_cause: Reasoning
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
    rationale: Reasoning
    blast_radius: str
    lockfile_change_reason: str | None = None


class FixResult(BaseModel):
    """What the rest of the system (scope guard, anticheat guard, verify)
    actually consumes -- a real unified diff, computed by fix.py from a
    FixProposal, never generated directly by the LLM.
    """

    diff: str
    rationale: Reasoning
    blast_radius: str
    lockfile_change_reason: str | None = None


class AntiCheatResult(BaseModel):
    rejected: bool
    reject_reasons: list[str]
    requires_human_review: bool
    review_reasons: list[str]


class TestRunSummary(BaseModel):
    """One `docker run`'s worth of pytest results, by test id. Stores both
    passed and failed names (not just counts) because run_verification needs
    the actual sets to compute regressions/newly_passing.
    """

    passed_tests: list[str]
    failed_tests: list[str]


class VerificationResult(BaseModel):
    """Deterministic, not LLM-backed (DECISIONS.md #21) -- two docker runs
    against the same pre-built image, diffed by test id. `passed` requires
    the patched suite to be fully green, not merely no-worse-than-baseline:
    a diff that neither fixes the target failure nor breaks anything else
    still shouldn't be reported as a passing verification.
    """

    baseline_summary: TestRunSummary
    patched_summary: TestRunSummary
    delta: str
    passed: bool
    regressions: list[str]
    newly_passing: list[str]
