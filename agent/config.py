import os

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://192.168.1.17:11434")

TRIAGE_MODEL = os.environ.get("TRIAGE_MODEL", "qwen3.5:0.8b")
TRIAGE_FALLBACK_MODEL = os.environ.get("TRIAGE_FALLBACK_MODEL", "qwen3.5:latest")
DIAGNOSIS_MODEL = os.environ.get("DIAGNOSIS_MODEL", "qwen3.5:latest")
FIX_MODEL = os.environ.get("FIX_MODEL", "qwen3-coder:30b")

ALL_CONFIGURED_MODELS = [TRIAGE_MODEL, TRIAGE_FALLBACK_MODEL, DIAGNOSIS_MODEL, FIX_MODEL]
