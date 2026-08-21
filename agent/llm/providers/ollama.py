import httpx

from agent.config import OLLAMA_BASE_URL
from agent.llm.interface import LLMProvider


class OllamaProvider(LLMProvider):
    provider_name = "ollama"

    def __init__(self, base_url: str = OLLAMA_BASE_URL):
        self.base_url = base_url

    def _raw_generate(self, model: str, prompt: str) -> tuple[str, dict]:
        resp = httpx.post(
            f"{self.base_url}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "format": "json",
                "stream": False,
                # qwen3.5 is a hybrid reasoning model: without this, its
                # final answer can end up in a separate "thinking" field
                # and "response" comes back empty (see LOG.md).
                "think": False,
            },
            timeout=180,
        )
        resp.raise_for_status()
        data = resp.json()
        tokens = data.get("prompt_eval_count", 0) + data.get("eval_count", 0)
        latency = data.get("total_duration", 0) / 1e9
        return data.get("response", ""), {"tokens": tokens, "latency": latency}
