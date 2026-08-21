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
