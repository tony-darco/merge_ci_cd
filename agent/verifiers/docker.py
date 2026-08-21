"""Local Docker verification backend -- the M3 implementation, unchanged in
behavior, now behind the Verifier interface (DECISIONS.md #27). Builds the
dependency-baked image once and mounts source + diff per run (#15).
"""

import json
import subprocess
import tempfile
from pathlib import Path

from agent.verifiers.base import Verifier

REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFY_IMAGE = "agentic-fixer-verify:base"


class DockerVerifier(Verifier):
    name = "docker"

    def __init__(self) -> None:
        self._image_built = False

    def _ensure_image_built(self) -> None:
        if self._image_built:
            return
        subprocess.run(
            ["docker", "build", "-f", "verify/Dockerfile", "-t", VERIFY_IMAGE, "."],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self._image_built = True

    def _run_suite(self, checkout_path: Path, diff_text: str | None) -> dict:
        self._ensure_image_built()
        patch_path = None
        if diff_text is not None:
            with tempfile.NamedTemporaryFile("w", suffix=".diff", delete=False) as f:
                f.write(diff_text)
                patch_path = Path(f.name)
        try:
            with tempfile.TemporaryDirectory(prefix="verify-out-") as out_dir:
                args = [
                    "docker", "run", "--rm",
                    "-v", f"{checkout_path}:/workspace/src:ro",
                    "-v", f"{out_dir}:/workspace/out",
                ]
                if patch_path is not None:
                    args += ["-v", f"{patch_path}:/workspace/patch.diff:ro"]
                args.append(VERIFY_IMAGE)
                subprocess.run(args, check=True, capture_output=True, text=True)
                return json.loads((Path(out_dir) / "results.json").read_text())
        finally:
            if patch_path is not None:
                patch_path.unlink(missing_ok=True)
