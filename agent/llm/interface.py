"""The single call surface every agent uses (spec §5.6, DECISIONS.md #7).
No agent talks to a vendor SDK directly -- swapping Ollama for a hosted
provider later means writing a new providers/*.py, not touching any agent.
"""

import time
from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class SchemaValidationFailure(Exception):
    pass


def _clean_json_text(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    return text


class LLMProvider(ABC):
    provider_name: str

    @abstractmethod
    def _raw_generate(self, model: str, prompt: str) -> tuple[str, dict]:
        """Returns (raw_response_text, meta). meta may include 'tokens' and 'latency'."""
        raise NotImplementedError

    def generate_structured(
        self, model: str, prompt: str, schema_cls: type[T], max_retries: int = 3
    ) -> tuple[T, dict]:
        last_error: Exception | None = None
        current_prompt = prompt
        for _ in range(max_retries):
            start = time.monotonic()
            raw, meta = self._raw_generate(model, current_prompt)
            wall_latency = time.monotonic() - start
            try:
                result = schema_cls.model_validate_json(_clean_json_text(raw))
                return result, {
                    "provider": self.provider_name,
                    "model": model,
                    "tokens": meta.get("tokens"),
                    "latency": meta.get("latency", wall_latency),
                    "raw": raw,
                }
            except (ValidationError, ValueError) as e:
                last_error = e
                current_prompt = (
                    f"{prompt}\n\nYour previous output failed schema validation because: "
                    f"{e}\nReturn ONLY valid JSON matching the schema, no other text."
                )
        raise SchemaValidationFailure(
            f"exhausted {max_retries} attempts for model {model!r}: {last_error}"
        )
