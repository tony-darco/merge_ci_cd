import os

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://192.168.1.17:11434")

TRIAGE_MODEL = os.environ.get("TRIAGE_MODEL", "qwen3.5:0.8b")
TRIAGE_FALLBACK_MODEL = os.environ.get("TRIAGE_FALLBACK_MODEL", "qwen3.5:latest")
DIAGNOSIS_MODEL = os.environ.get("DIAGNOSIS_MODEL", "qwen3.5:latest")
FIX_MODEL = os.environ.get("FIX_MODEL", "qwen3-coder:30b")

ALL_CONFIGURED_MODELS = [TRIAGE_MODEL, TRIAGE_FALLBACK_MODEL, DIAGNOSIS_MODEL, FIX_MODEL]

# Verification backend (DECISIONS.md #27): "docker" locally, "argo" inside
# the cluster. The orchestrator's verify node is identical either way.
VERIFIER = os.environ.get("VERIFIER", "docker")
SANDBOX_NAMESPACE = os.environ.get("SANDBOX_NAMESPACE", "agentic-fixer-sandbox")
VERIFY_WORKFLOW_TEMPLATE = os.environ.get("VERIFY_WORKFLOW_TEMPLATE", "agentic-fixer-verify-wft")
SAMPLE_APP_REPO = os.environ.get("SAMPLE_APP_REPO", "https://github.com/tony-darco/sample-app.git")
