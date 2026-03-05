from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class TurnSnargle:
    """
    Pre-CTO ingress object.

    A TurnSnargle is submitted to the hub. The hub validates it, then creates a CTO
    and emits `cto_created`.

    Working name deliberately repellant to motivate prompt replacement.
    """

    session_id: UUID
    content_profile: str
    content: dict[str, Any]

    # optional caller correlation / idempotency hooks (v0: nullable)
    request_id: str | None = None

    # optional provenance label when not submitted by a Purpose
    submitted_by_label: str | None = None
