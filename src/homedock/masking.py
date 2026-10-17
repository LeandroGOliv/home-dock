"""Masking of secrets and identifiers (local keys, device IDs, IPs) for logs and messages.

Layer-independent leaf module: any layer may import it.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable

# Four dotted numbers, not part of a longer dotted number (a trailing "." is punctuation).
IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?!\.?\d)")


def mask(value: object) -> str:
    """Mask a value for display, keeping only its first and last two characters."""
    text = "" if value is None else str(value)
    if not text:
        return "(empty)"
    if len(text) <= 4:
        return "…"
    return f"{text[:2]}…{text[-2:]}"


def redact(text: str, secrets: Iterable[object]) -> str:
    """Replace every occurrence of each secret in ``text`` (ignoring case) by its masked form."""
    values = {str(s) for s in secrets if s}
    for secret in sorted(values, key=len, reverse=True):
        pattern = re.compile(re.escape(secret), re.IGNORECASE)
        text = pattern.sub(lambda m: mask(m.group()), text)
    return text


class RedactingFilter(logging.Filter):
    """Logging filter that masks known secrets and any IPv4 address in each record.

    Covers the formatted message, the exception text and the stack info. Attach it to a
    handler so it also sees the records of third-party loggers.
    """

    def __init__(self) -> None:
        super().__init__()
        self._secrets: set[str] = set()

    def add(self, *secrets: object) -> None:
        self._secrets.update(str(s) for s in secrets if s)

    def redact(self, text: str) -> str:
        return IPV4.sub(lambda m: mask(m.group()), redact(text, self._secrets))

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = self.redact(message)
        if redacted != message:
            record.msg, record.args = redacted, None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = self.redact(record.exc_text)
        if record.stack_info:
            record.stack_info = self.redact(record.stack_info)
        return True
