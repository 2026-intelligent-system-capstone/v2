from __future__ import annotations

import re

SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"\b([A-Z0-9_.-]*(?:API[_-]?KEY|SECRET|TOKEN|PASSWORD|AUTHORIZATION|BEARER)[A-Z0-9_.-]*)\b"
    r"\s*[:=]\s*"
    r"([^\s,;]+)",
    re.IGNORECASE,
)
OPENAI_KEY_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")
AWS_ACCESS_KEY_PATTERN = re.compile(r"\bA[KS]IA[0-9A-Z]{16}\b")
JWT_PATTERN = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")


def redact_sensitive_text(text: str) -> str:
    redacted = OPENAI_KEY_PATTERN.sub("[REDACTED_SECRET]", text)
    redacted = AWS_ACCESS_KEY_PATTERN.sub("[REDACTED_SECRET]", redacted)
    redacted = JWT_PATTERN.sub("[REDACTED_SECRET]", redacted)
    return SECRET_ASSIGNMENT_PATTERN.sub(
        lambda match: f"{match.group(1)}=[REDACTED_SECRET]",
        redacted,
    )
