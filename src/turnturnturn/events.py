from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any
from uuid import UUID


class HubEventType(str, Enum):
    """
    Hub-authoritative lifecycle events.

    Naming principle:
      - event_type names what *the hub* has made true
      - avoid receiver-relative terms (“received”, “seen”, etc.)
    """

    CTO_CREATED = "cto_created"
    DELTA_MERGED = "delta_merged"
    PURPOSE_REGISTERED = "purpose_registered"
    PURPOSE_COMPLETED = "purpose_completed"
    # add TURN_COMPLETED later if needed


@dataclass(frozen=True)
class HubEvent:
    """
    The event envelope.

    `turn_id` is nullable because some events are not scoped to a CTO
    (e.g., purpose registration, session lifecycle).
    """

    event_type: HubEventType
    event_id: UUID
    created_at_ms: int

    session_id: UUID | None = None
    turn_id: UUID | None = None

    payload: dict[str, Any] | None = None


def payload_cto_created(
    *,
    cto_dict: dict[str, Any],
    submitted_by_purpose_id: str | None = None,
    submitted_by_purpose_name: str | None = None,
    submitted_by_label: str | None = None,
) -> dict[str, Any]:
    return {
        "_schema": "cto_created",
        "_v": 1,
        "cto": cto_dict,
        "submitted_by_purpose_id": submitted_by_purpose_id,
        "submitted_by_purpose_name": submitted_by_purpose_name,
        "submitted_by_label": submitted_by_label,
    }
