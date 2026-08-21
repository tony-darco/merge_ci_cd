"""Verification entrypoint. The actual backends live in agent/verifiers/
(DECISIONS.md #27) -- this stays as the stable call site the rest of the
system and its tests already use.
"""

from pathlib import Path

from agent.llm.schema import VerificationResult
from agent.verifiers import get_verifier


def run_verification(pre_fix_checkout: Path, diff_text: str) -> VerificationResult:
    return get_verifier().run(pre_fix_checkout, diff_text)
