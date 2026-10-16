"""Masking of secrets and identifiers (local keys, device IDs, IPs) for logs and messages.

Layer-independent leaf module: any layer may import it.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable


def mask(value: object) -> str:
    """Mask a value for display, keeping only its first and last two characters."""
    text = "" if value is None else str(value)
    if not text:
        return "(empty)"
    if len(text) <= 4:
        return "…"
    return f"{text[:2]}…{text[-2:]}"


def redact(text: str, secrets: Iterable[object]) -> str:
    """Replace every occurrence of each secret in ``text`` by its masked form."""
    values = {str(s) for s in secrets if s}
    for secret in sorted(values, key=len, reverse=True):
        text = text.replace(secret, mask(secret))
    return text


class RedactingFilter(logging.Filter):
    """Logging filter that masks known secrets in the formatted message of each record."""

    def __init__(self) -> None:
        super().__init__()
        self._secrets: set[str] = set()

    def add(self, *secrets: object) -> None:
        self._secrets.update(str(s) for s in secrets if s)

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = redact(message, self._secrets)
        if redacted != message:
            record.msg, record.args = redacted, None
        return True
