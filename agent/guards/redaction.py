"""Secret redaction (spec §7.2): logs routinely contain tokens, connection
strings, and env dumps. Scrubbed before any log content leaves this process
-- applied before slicing, so a truncated slice can't reintroduce a secret
that would've been cut by redaction running the other way around.
"""

import re

_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key id
    re.compile(r"ghp_[A-Za-z0-9]{36}"),  # GitHub personal access token
    re.compile(r"(?i)api[_-]?key\s*[:=]\s*['\"]?[A-Za-z0-9\-_]{12,}"),
    re.compile(r"(?i)\bsecret\b\s*[:=]\s*['\"]?[A-Za-z0-9\-_]{12,}"),
    re.compile(r"(?i)password\s*[:=]\s*['\"]?\S+"),
    re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]+?"
        r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
    ),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9\-_.]{16,}"),
]


def redact(text: str) -> str:
    result = text
    for pattern in _PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result
