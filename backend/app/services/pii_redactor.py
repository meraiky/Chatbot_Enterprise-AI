from __future__ import annotations

import re


PII_PATTERNS = {
    # Vietnamese identifiers
    "phone_vn": r"(?<!\d)(?:\+84|0)[3-9]\d{8}(?!\d)",
    "cccd": r"(?<!\d)\d{12}(?!\d)",
    "tax_id": r"(?<!\d)\d{10}(?:-\d{3})?(?!\d)",
    # Universal
    "email": r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    "credit_card": r"(?<!\d)\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}(?!\d)",
    "iban": r"\b[A-Z]{2}\d{2}[A-Z0-9]{4}\d{7}(?:[A-Z0-9]{0,16})\b",
    "passport": r"\b[A-Z]{1,2}\d{6,9}\b",
    # JWT / API key patterns (users sometimes paste these into chat)
    "jwt_token": r"eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+",
    "api_key_generic": r"\b(?:sk|pk|ak|api)[_\-][A-Za-z0-9]{20,}\b",
}

# W-6 fix: pre-compile regexes at module level for consistency with injection_scanner.py
_COMPILED_PII = {k: re.compile(p) for k, p in PII_PATTERNS.items()}


def redact(text: str) -> str:
    redacted = text or ""
    for pii_type, compiled in _COMPILED_PII.items():
        redacted = compiled.sub(f"[{pii_type.upper()}_REDACTED]", redacted)
    return redacted
