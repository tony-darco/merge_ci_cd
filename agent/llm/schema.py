from pydantic import BaseModel


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
