"""Hub-authored event definitions and payload classes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any
from uuid import UUID

from ..protocols import EventPayloadProtocol


class HubEventType(str, Enum):
    """
    Hub-authoritative lifecycle and routing events.

    Naming principle:
      - event_type names what the hub has made true
      - avoid receiver-relative terms ("received", "seen", etc.)
    """

    CTO_CREATED = "cto_created"
    DELTA_MERGED = "delta_merged"
    PURPOSE_STARTED = "purpose_started"


@dataclass(frozen=True)
class EmptyPayload(EventPayloadProtocol):
    """Payload for events that carry no additional structured data."""

    def as_dict(self) -> dict[str, Any]:
        return {}


@dataclass(frozen=True)
class CTOCreatedPayload(EventPayloadProtocol):
    """
    Payload for a cto_created HubEvent.

    Carries a CTOIndex as a lightweight routing reference and optional
    submitter attribution. Purposes that need full CTO state call
    ttt.librarian.get_cto(turn_id).
    """

    cto_index: dict[str, Any]
    submitted_by_purpose_id: str | None = None
    submitted_by_purpose_name: str | None = None
    submitted_by_label: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "_schema": "cto_created",
            "_v": 1,
            "cto_index": self.cto_index,
            "submitted_by_purpose_id": self.submitted_by_purpose_id,
            "submitted_by_purpose_name": self.submitted_by_purpose_name,
            "submitted_by_label": self.submitted_by_label,
        }


@dataclass(frozen=True)
class DeltaMergedPayload(EventPayloadProtocol):
    """
    Payload for a delta_merged HubEvent.

    Carries the full serialized Delta for provenance and a CTOIndex dict as
    a lightweight routing reference. Purposes that need full CTO state call
    ttt.librarian.get_cto(turn_id).
    """

    delta: dict[str, Any]
    cto_index: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "_schema": "delta_merged",
            "_v": 1,
            "delta": self.delta,
            "cto_index": self.cto_index,
        }


@dataclass(frozen=True)
class HubEvent:
    """
    Hub-authored event envelope delivered on the downlink to registered
    Purposes.

    `turn_id` is nullable because some events are not scoped to a CTO
    (e.g., purpose registration, session lifecycle).

    `hub_token` and `downlink_signature` are stamped per-recipient at dispatch
    time. BasePurpose.take_turn() validates both before delegating to
    _handle_event().
    """

    event_type: HubEventType
    event_id: UUID
    created_at_ms: int

    session_id: UUID | None = None
    turn_id: UUID | None = None
    payload: EventPayloadProtocol = EmptyPayload()

    # Set by hub at dispatch time. None only for raw/test recipients that do
    # not participate in BasePurpose validation.
    hub_token: str | None = None
    downlink_signature: str | None = None
