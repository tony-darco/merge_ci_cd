# Verification image: dependencies baked in, built once (rebuilt only when
# sample-app/requirements.txt changes). Source and an optional patch are
# supplied at `docker run` time via bind mounts, not baked into the image --
# this is what makes iterating on a candidate fix a `docker run` instead of
# a multi-minute `docker build` per attempt (DECISIONS.md #15).
#
# Build from the repo root: docker build -f verify/Dockerfile -t agentic-fixer-verify:base .
FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends patch && rm -rf /var/lib/apt/lists/*
COPY sample-app/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY verify/entrypoint.sh /usr/local/bin/verify-entrypoint.sh
COPY verify/parse_results.py /usr/local/bin/parse_results.py
RUN chmod +x /usr/local/bin/verify-entrypoint.sh
WORKDIR /workspace
ENTRYPOINT ["/usr/local/bin/verify-entrypoint.sh"]
