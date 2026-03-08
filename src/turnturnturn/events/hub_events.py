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

    SESSION_STARTED is emitted as the hub's first act, written directly
    to the persistence Purpose before any other registration or dispatch.
    It predates the event mesh and is never multicast.
    """

    CTO_CREATED = "cto_created"
    DELTA_MERGED = "delta_merged"
    PURPOSE_STARTED = "purpose_started"
    SESSION_STARTED = "session_started"


@dataclass(frozen=True)
class EmptyPayload(EventPayloadProtocol):
    """
    Payload for events that carry no additional structured data.

    Retained for test construction convenience. Not used for
    purpose_started events in production — those carry PurposeStartedPayload.
    """

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
class SessionStartPayload(EventPayloadProtocol):
    """
    Payload for the session_started HubEvent.

    Emitted as the hub's first act — written directly to the persistence
    Purpose before any other registration or dispatch. This is the first
    record in every event log and provides provenance about the provenance
    mechanism itself: which hub instance produced this log, which backend
    is storing it, and whether that backend is durable.

    hub_id identifies this hub instance across sessions. ttt_version
    allows the event log to be interpreted correctly during replay against
    future TTT versions. persister_is_durable is recorded here so that
    audit consumers can immediately determine whether the log they are
    reading is a durable record or a development artifact.
    """

    hub_id: str  # UUID as string; minted at TTT.start()
    ttt_version: str  # from importlib.metadata
    persister_name: str
    persister_id: str  # UUID as string
    persister_is_durable: bool
    strict_profiles: bool
    created_at_ms: int

    def as_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict for the event log."""
        return {
            "_schema": "session_started",
            "_v": 1,
            "hub_id": self.hub_id,
            "ttt_version": self.ttt_version,
            "persister_name": self.persister_name,
            "persister_id": self.persister_id,
            "persister_is_durable": self.persister_is_durable,
            "strict_profiles": self.strict_profiles,
            "created_at_ms": self.created_at_ms,
        }


@dataclass(frozen=True)
class PurposeStartedPayload(EventPayloadProtocol):
    """
    Payload for a purpose_started HubEvent.

    Emitted by the hub on each start_purpose() call after the persister
    is bootstrapped. is_persistence_purpose enables audit reconstruction
    of session participants and their roles — specifically, whether the
    registrant is part of the persistence layer or a domain Purpose.
    """

    purpose_name: str
    purpose_id: str  # UUID as string
    is_persistence_purpose: bool
    created_at_ms: int

    def as_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict for the event log."""
        return {
            "_schema": "purpose_started",
            "_v": 1,
            "purpose_name": self.purpose_name,
            "purpose_id": self.purpose_id,
            "is_persistence_purpose": self.is_persistence_purpose,
            "created_at_ms": self.created_at_ms,
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
