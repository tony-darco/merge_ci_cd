"""Queries the Ollama host for what's actually pulled (spec §5.6) -- model
availability on a local host is a moving target, never assumed.
"""

import httpx

from agent.config import OLLAMA_BASE_URL


class ModelNotAvailableError(Exception):
    pass


def list_available_models(base_url: str = OLLAMA_BASE_URL) -> list[str]:
    resp = httpx.get(f"{base_url}/api/tags", timeout=10)
    resp.raise_for_status()
    return [m["name"] for m in resp.json().get("models", [])]


def get_context_window(model_name: str, base_url: str = OLLAMA_BASE_URL) -> int:
    resp = httpx.post(f"{base_url}/api/show", json={"name": model_name}, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    model_info = data.get("model_info", {})
    family = data.get("details", {}).get("family")
    key = f"{family}.context_length"
    if family and key in model_info:
        return model_info[key]
    for k, v in model_info.items():
        if k.endswith(".context_length"):
            return v
    raise ModelNotAvailableError(f"could not determine context window for {model_name!r}")


def validate_model_available(model_name: str, base_url: str = OLLAMA_BASE_URL) -> None:
    available = list_available_models(base_url)
    if model_name not in available:
        raise ModelNotAvailableError(
            f"model {model_name!r} is not available on {base_url}. "
            f"Pulled models: {', '.join(sorted(available)) or '(none)'}"
        )
