"""Helpers shared by the user's named collections (groups, scenes)."""

from __future__ import annotations

import uuid


def clean_name(name: str) -> str:
    """The trimmed name; raises ``ValueError`` when it is blank."""
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("name must not be blank")
    return cleaned


def new_uuid() -> str:
    return uuid.uuid4().hex
