from agent.llm.interface import LLMProvider


class NeverCalledProvider(LLMProvider):
    """Spy provider that fails the test if the LLM is ever actually invoked --
    used to prove a deterministic guard short-circuited before any LLM call.
    """

    provider_name = "never-called"

    def _raw_generate(self, model: str, prompt: str) -> tuple[str, dict]:
        raise AssertionError("LLM provider was called, but a deterministic guard should have short-circuited first")


class ScriptedProvider(LLMProvider):
    """Provider that returns a scripted sequence of (raw_text_or_exception)
    responses per model name, for exercising retry/fallback logic without
    hitting a real LLM.
    """

    provider_name = "scripted"

    def __init__(self, responses_by_model: dict[str, list[str | Exception]]):
        self._queues = {k: list(v) for k, v in responses_by_model.items()}
        self.calls: list[tuple[str, str]] = []

    def _raw_generate(self, model: str, prompt: str) -> tuple[str, dict]:
        self.calls.append((model, prompt))
        queue = self._queues.get(model)
        if not queue:
            raise AssertionError(f"ScriptedProvider has no more responses queued for model {model!r}")
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item, {"tokens": 1, "latency": 0.0}
