"""Runtime decision trace (spec §9.2). Every agent decision from M1 onward
records one of these -- it's the same data that becomes the M6 PR trace and
the audit trail, built once. A TraceEvent with empty reasoning is a bug, not
a logging gap: the validator below raises rather than silently degrading.
"""

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, field_validator

TRACES_DIR = Path(__file__).resolve().parent.parent / "traces"

_run_id = os.environ.get("AGENT_RUN_ID") or str(uuid.uuid4())
_events: list["TraceEvent"] = []


class TraceEvent(BaseModel):
    timestamp: str
    actor: str  # orchestrator / triage / diagnosis / fix / verify
    decision: str
    reasoning: str
    evidence: list[str] = []
    alternatives_rejected: list[str] = []
    inputs_hash: str
    model: str | None = None
    provider: str | None = None
    tokens: int | None = None
    latency: float | None = None

    @field_validator("reasoning")
    @classmethod
    def reasoning_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError(
                "TraceEvent.reasoning must not be empty -- a decision with no "
                "reasoning is a bug, not a logging gap"
            )
        return v


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def inputs_hash(inputs: Any) -> str:
    canonical = json.dumps(inputs, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def set_run_id(run_id: str) -> None:
    global _run_id
    _run_id = run_id


def record_trace(event: TraceEvent) -> None:
    _events.append(event)
    TRACES_DIR.mkdir(parents=True, exist_ok=True)
    with (TRACES_DIR / f"{_run_id}.jsonl").open("a") as f:
        f.write(event.model_dump_json() + "\n")


def get_events() -> list[TraceEvent]:
    return list(_events)


def clear_events() -> None:
    _events.clear()
