# The agent image, used for both steps of the exit hook (DECISIONS.md #29):
# `fetch-source` (git clone at the failing commit) and `run-agent`
# (context_builder -> the orchestrator graph).
#
# Ships kubectl and git, but deliberately NOT the argo CLI: workflow status
# is read via kubectl since Argo Workflows are just a CRD, which keeps this
# image smaller and avoids depending on argo-server being reachable from
# inside a pod (DECISIONS.md #26).
FROM python:3.13-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends git curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# kubectl, pinned to the cluster's minor version.
ARG KUBECTL_VERSION=v1.33.0
RUN curl -fsSLo /usr/local/bin/kubectl \
      "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/$(dpkg --print-architecture)/kubectl" \
 && chmod +x /usr/local/bin/kubectl

WORKDIR /app

# Dependencies first so agent/ edits don't invalidate the install layer.
COPY pyproject.toml uv.lock README.md ./
RUN pip install --no-cache-dir \
      "pydantic>=2" "httpx>=0.27" "unidiff>=0.7" "langgraph>=1.2.11"

COPY agent/ ./agent/
COPY fixtures/ ./fixtures/

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    VERIFIER=argo

# No ENTRYPOINT: each DAG step supplies its own command.
CMD ["python", "-c", "print('agentic-fixer agent image; supply a command')"]
