from __future__ import annotations

import re

from app.services.pii_redactor import redact as redact_pii


SECRET_PATTERNS = {
    "jwt": r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+",
    "openai_key": r"\bsk-[A-Za-z0-9_-]{20,}\b",
    "anthropic_key": r"\bsk-ant-[A-Za-z0-9_-]{20,}\b",
    "google_key": r"\bAIza[A-Za-z0-9_-]{30,}\b",
    "assignment_secret": (
        r"(?i)\b("
        r"api[_-]?key|token|secret|password|passwd|pwd|authorization|"
        r"jwt[_-]?secret[_-]?key|encryption[_-]?key|redis[_-]?password|"
        r"postgres[_-]?password|database[_-]?url|redis[_-]?url"
        r")\b\s*[:=]\s*([^\s,;]+)"
    ),
    "url_password": r"(?P<scheme>[a-z][a-z0-9+.-]*://[^:\s/@]+):(?P<password>[^@\s/]+)@",
}


def redact_sensitive(text: object) -> str:
    """Remove secrets and PII before a message is written to logs or debug responses."""
    redacted = redact_pii(str(text or ""))
    redacted = re.sub(SECRET_PATTERNS["jwt"], "[JWT_REDACTED]", redacted)
    redacted = re.sub(SECRET_PATTERNS["openai_key"], "[OPENAI_KEY_REDACTED]", redacted)
    redacted = re.sub(SECRET_PATTERNS["anthropic_key"], "[ANTHROPIC_KEY_REDACTED]", redacted)
    redacted = re.sub(SECRET_PATTERNS["google_key"], "[GOOGLE_KEY_REDACTED]", redacted)
    redacted = re.sub(
        SECRET_PATTERNS["assignment_secret"],
        lambda match: f"{match.group(1)}=[SECRET_REDACTED]",
        redacted,
    )
    redacted = re.sub(
        SECRET_PATTERNS["url_password"],
        lambda match: f"{match.group('scheme')}:[PASSWORD_REDACTED]@",
        redacted,
    )
    return redacted
