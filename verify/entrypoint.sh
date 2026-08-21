#!/bin/sh
# Copies the mounted source into a scratch dir (never mutates the read-only
# mount), applies /workspace/patch.diff if present, runs the full suite,
# and writes /workspace/out/results.json -- regardless of whether the suite
# passed, or even ran at all, so the host side always gets a real result to
# compare instead of having to infer failure from a missing file or a hung
# container (see LOG.md -- a bad patch under `set -e` used to exit before
# ever writing output).
set -u

mkdir -p /workspace/run /workspace/out
cp -r /workspace/src/. /workspace/run/
cd /workspace/run

# -s, not -f: the file must exist AND be non-empty. Under Docker the file
# is simply absent for a baseline run, but Argo supplies it as a `raw`
# artifact that's always created and is zero-byte for the baseline --
# feeding that to `patch` yields "only garbage was found in the patch
# input". An empty patch means "no patch" either way.
if [ -s /workspace/patch.diff ]; then
    if ! patch -p1 --forward --batch < /workspace/patch.diff; then
        echo '{"tests": {}, "patch_applied": false}' > /workspace/out/results.json
        exit 0
    fi
fi

# PYTHONPATH rather than `pip install -e .`: an editable install triggers a
# PEP 517 build that reaches out to PyPI for setuptools, which the sandbox
# namespace's egress allowlist correctly denies (see LOG.md) -- the isolation
# is working as designed, so the install step is what has to stop needing the
# network. The sample app is a src layout, so this makes it importable with
# no build step, no download, and identical behavior under Docker.
export PYTHONPATH=/workspace/run/src:${PYTHONPATH:-}

python -m pytest -q --tb=no --junitxml=/workspace/out/results.xml || true
python /usr/local/bin/parse_results.py /workspace/out/results.xml /workspace/out/results.json
