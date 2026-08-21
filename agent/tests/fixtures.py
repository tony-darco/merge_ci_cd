import json
from pathlib import Path

from agent.llm.schema import FailureContext

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures"


def load_fixture(name: str) -> FailureContext:
    data = json.loads((FIXTURES_DIR / name / "context.json").read_text())
    return FailureContext.model_validate(data)
