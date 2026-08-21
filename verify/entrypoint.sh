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

if [ -f /workspace/patch.diff ]; then
    if ! patch -p1 --forward --batch < /workspace/patch.diff; then
        echo '{"tests": {}, "patch_applied": false}' > /workspace/out/results.json
        exit 0
    fi
fi

pip install --no-cache-dir -e . --quiet

python -m pytest -q --tb=no --junitxml=/workspace/out/results.xml || true
python /usr/local/bin/parse_results.py /workspace/out/results.xml /workspace/out/results.json
