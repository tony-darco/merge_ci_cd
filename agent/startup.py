"""Called first by any entrypoint that will make LLM calls (spec §5.6):
fail fast with a clear message if a configured model isn't actually pulled,
rather than discovering it mid-run.
"""

import sys

from agent.config import ALL_CONFIGURED_MODELS
from agent.llm.registry import ModelNotAvailableError, validate_model_available


def validate_models() -> None:
    for model in ALL_CONFIGURED_MODELS:
        validate_model_available(model)


if __name__ == "__main__":
    try:
        validate_models()
    except ModelNotAvailableError as e:
        print(f"startup check failed: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"all {len(ALL_CONFIGURED_MODELS)} configured models available")
