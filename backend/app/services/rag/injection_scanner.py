from __future__ import annotations

import re
import unicodedata

INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions?",
    r"ignore\s+(the\s+)?(?:above|prior|earlier)\s+(?:instructions?|rules|prompt)",
    r"disregard\s+your\s+system\s+prompt",
    r"(?:reveal|print|show|repeat|dump|leak)\s+(?:the\s+)?(?:system\s+)?(?:prompt|instructions?|developer\s+message|hidden\s+rules)",
    r"(?:system|developer|assistant)\s*:\s*you\s+(?:must|will|are)",
    r"you\s+are\s+now\s+a\s+different\s+ai",
    r"act\s+as\s+(?:if\s+you\s+are\s+)?(?:dan|jailbreak|unrestricted|uncensored)",
    r"(?:developer|debug|maintenance|admin)\s+mode\s+(?:enabled|on|activated)",
    r"(?:do\s+anything\s+now|dan\s+mode|jailbreak\s+mode)",
    r"new\s+instructions?\s*:",
    r"override\s+(?:all\s+)?(?:safety|security|policy|instructions?|rules)",
    r"bypass\s+(?:all\s+)?(?:safety|security|policy|guardrails?|filters?)",
    r"base64\s+(?:decode|encoded)\s+instructions?",
    r"rot13|unicode\s+escape|hidden\s+message",
    r"<\s*(?:system|developer|instruction|prompt)\s*>",
    r"\[\s*(?:system|developer|instruction|prompt)\s*\]",
    r"(?:bo\s+qua|bỏ\s+qua)\s+(?:tat\s+ca\s+)?(?:huong\s+dan|hướng\s+dẫn|quy\s+tac|quy\s+tắc)",
    r"(?:tu\s+bay\s+gio|từ\s+bây\s+giờ)\s+(?:ban|bạn)\s+(?:la|là)",
    r"(?:tiet\s+lo|tiết\s+lộ|in\s+ra)\s+(?:system\s+prompt|prompt\s+he\s+thong|prompt\s+hệ\s+thống)",
]

# N-2: Pre-compile all patterns once at module load — avoids re-compilation on every user query.
# Python's re module has an internal cache, but explicit pre-compilation eliminates cache-lookup
# overhead entirely, which matters since scan_chunk() is now called on every chat request.
_COMPILED_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS
]


def _normalize(text: str) -> str:
    text = (text or "").lower()
    text = unicodedata.normalize("NFKC", text)
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf")


def scan_chunk(text: str) -> dict:
    """Scan text for prompt-injection patterns. Uses pre-compiled regexes (N-2)."""
    normalized = _normalize(text)
    findings = [
        p.pattern
        for p in _COMPILED_PATTERNS
        if p.search(normalized)
    ]
    return {
        "clean": not findings,
        "findings": findings,
        "risk_score": min(len(findings) / 3, 1.0),
    }


def sanitize_chunk(text: str) -> str:
    """Sanitize text by redacting injection patterns. Uses pre-compiled regexes (N-2)."""
    sanitized = text or ""
    for compiled in _COMPILED_PATTERNS:
        sanitized = compiled.sub("[REDACTED_INSTRUCTION]", sanitized)
    return sanitized
