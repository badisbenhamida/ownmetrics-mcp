"""Scrub secrets from any text that might reach a user, a log or an AI app (C5, AC5)."""

from __future__ import annotations

import logging
import re

REDACTED = "[redacted]"

# Bearer tokens are JWTs: three base64url segments separated by dots.
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_AUTH_HEADER = re.compile(r"(?i)\b(ApiKey|Bearer)\s+[^\s'\"]+")

_secrets: set[str] = set()


def register_secret(value: str | None) -> None:
    """Remember a secret (API key or token) so it is scrubbed everywhere."""
    if value and len(value) >= 8:
        _secrets.add(value)


def redact(text: str) -> str:
    for secret in sorted(_secrets, key=len, reverse=True):
        text = text.replace(secret, REDACTED)
    text = _AUTH_HEADER.sub(lambda m: f"{m.group(1)} {REDACTED}", text)
    return _JWT.sub(REDACTED, text)


class RedactingFilter(logging.Filter):
    """Applied to every handler so nothing secret is ever logged."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = ()
        return True


def install_log_redaction() -> None:
    root = logging.getLogger()
    for handler in root.handlers:
        handler.addFilter(RedactingFilter())
    for name in ("garmin_personal_api", "mcp", "ownmetrics_mcp", "urllib3", "requests"):
        logging.getLogger(name).addFilter(RedactingFilter())
