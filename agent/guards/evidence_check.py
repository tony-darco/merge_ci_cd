"""Empty/truncated logs (spec §7.2): a pod killed before flushing stdout
must degrade to "insufficient evidence," never hallucinate a cause.
"""

_MIN_LENGTH = 40


def has_sufficient_evidence(sliced_log: str, min_length: int = _MIN_LENGTH) -> bool:
    if not sliced_log or not sliced_log.strip():
        return False
    return len(sliced_log.strip()) >= min_length
