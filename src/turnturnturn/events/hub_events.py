"""Hub-authored event definitions and payload classes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any
from uuid import UUID

from ..delta import Delta
from ..protocols import EventPayloadProtocol


class HubEventType(str, Enum):
    """
    Hub-authoritative lifecycle and routing events.

    Naming principle:
      - event_type names what the hub has made true
      - avoid receiver-relative terms ("received", "seen", etc.)

    Delivery destinations (see _multicast() in hub.py):
      - Most events are multicast to all registered Purposes.
      - SESSION_STARTED and SESSION_COMPLETED are persistence-only —
        written directly to the persistence backend, never multicast.
        SESSION_STARTED predates the event mesh entirely; SESSION_COMPLETED
        follows after domain Purposes have cleared.

    v0.20 taxonomy (retired → replacement in migration notes):
      CTO_CREATED → CTO_STARTED
    """

    # CTO lifecycle
    CTO_STARTED = "cto_started"  # replaces CTO_CREATED (retired in v0.20)
    CTO_COMPLETED = "cto_completed"  # quiescence / CTOCloseRequest (stub)

    # Delta lifecycle
    DELTA_MERGED = "delta_merged"
    DELTA_REJECTED = "delta_rejected"  # malformed proposal; exception still raised

    # Purpose lifecycle
    PURPOSE_STARTED = "purpose_started"

    # Session lifecycle
    SESSION_STARTED = "session_started"  # persistence-only; first event in log
    SESSION_CLOSING = "session_closing"  # broadcast; evacuation signal to all Purposes
    SESSION_COMPLETED = "session_completed"  # persistence-only; final record


@dataclass(frozen=True)
class EmptyPayload(EventPayloadProtocol):
    """
    Payload for events that carry no additional structured data.

    Retained for test construction convenience. Not used for
    purpose_started events in production — those carry PurposeStartedPayload.
    """

    def as_dict(self) -> dict[str, Any]:
        """Return an empty dict — this payload carries no structured data."""
        return {}


@dataclass(frozen=True)
class CTOStartedPayload(EventPayloadProtocol):
    """
    Payload for a cto_started HubEvent.

    Carries a CTOIndex as a lightweight routing reference and submitter
    attribution. Purposes that need full CTO state call
    ttt.librarian.get_cto(turn_id).

    Replaces startedCTOStartedPayload (retired in v0.20). submitted_by_label has
    been removed — submitter attribution is always via Purpose identity.
    """

    cto_index: dict[str, Any]
    submitted_by_purpose_id: str | None = None
    submitted_by_purpose_name: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict for the event log."""
        return {
            "_schema": "cto_started",
            "_v": 1,
            "cto_index": self.cto_index,
            "submitted_by_purpose_id": self.submitted_by_purpose_id,
            "submitted_by_purpose_name": self.submitted_by_purpose_name,
        }


@dataclass(frozen=True)
class CTOCompletedPayload(EventPayloadProtocol):
    """
    Payload for a cto_completed HubEvent.

    Carries the full CTO dict so that Archivist backends need no librarian
    reference when recording the terminal state of a CTO. This is the one
    place a full snapshot travels on the event bus; all other CTO events
    carry only a CTOIndex.

    cto_dict is the output of CTO serialization at quiescence time. Its
    shape mirrors cto_snapshot_record() in _event_serialization.py.
    """

    cto_dict: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict for the event log."""
        return {
            "_schema": "cto_completed",
            "_v": 1,
            "cto_dict": self.cto_dict,
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
        """Serialize to a JSON-safe dict for the event log."""
        return {
            "_schema": "delta_merged",
            "_v": 1,
            "delta": self.delta,
            "cto_index": self.cto_index,
        }


@dataclass(frozen=True)
class DeltaRejectedPayload(EventPayloadProtocol):
    """
    Payload for a delta_rejected HubEvent.

    Emitted by the hub when a Delta proposal fails validation. The hub
    still raises the underlying ValueError/KeyError after emission so
    callers are not silently swallowed — the event is a provenance record
    of the rejection, not a replacement for the exception.

    delta_dict carries the rejected Delta serialization (may be partial if
    the rejection was structural). reason is a human-readable explanation
    suitable for logging and audit.
    """

    delta_dict: dict[str, Any]
    reason: str

    def as_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict for the event log."""
        return {
            "_schema": "delta_rejected",
            "_v": 1,
            "delta_dict": self.delta_dict,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class DeltaProposalPayload(EventPayloadProtocol):
    """
    Payload for a Purpose-originated delta proposal.

    Moved here from purpose_events.py in v0.20 — it belongs alongside the
    other payload classes. The import path through events/__init__.py is
    preserved; consuming code that imported from purpose_events directly
    should migrate to importing from events or events.hub_events.

    This is a proposal, not a hub-authored fact. The hub validates the
    submitting Purpose and decides whether and how the proposal becomes
    canonical state.
    """

    delta: Delta

    def as_dict(self) -> dict[str, object]:
        """Serialize to a JSON-safe dict. Returns the Delta's own dict form."""
        return {"delta": self.delta.to_dict()}


@dataclass(frozen=True)
class SessionStartedPayload(EventPayloadProtocol):
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

    Renamed from SessionStartPayload in v0.20 for consistency with the
    event name (SESSION_STARTED). SessionStartPayload is kept as a
    deprecated alias for one version.
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


# Deprecated alias — kept for one version so consuming code has time to migrate.
# Remove in v0.21.
SessionStartPayload = SessionStartedPayload


@dataclass(frozen=True)
class SessionClosingPayload(EventPayloadProtocol):
    """
    Payload for a session_closing HubEvent.

    Broadcast to all registered Purposes by ttt.close(). Domain Purposes
    use this as their evacuation signal: flush in-flight state, submit
    any final Deltas, and send PURPOSE_COMPLETED to the hub.

    reason is a human-readable string (e.g. "normal", "timeout"). It is
    recorded in the event log so audit consumers can distinguish planned
    shutdowns from forced ones.

    timeout_ms, if present, is the number of milliseconds the hub will
    wait for domain Purposes to clear before emitting SESSION_COMPLETED
    regardless. None means no timeout is enforced (v0 behaviour).
    Quiescence-triggered timeout logic is deferred to the DAG layer.
    """

    reason: str
    timeout_ms: int | None = None

    def as_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict for the event log."""
        return {
            "_schema": "session_closing",
            "_v": 1,
            "reason": self.reason,
            "timeout_ms": self.timeout_ms,
        }


@dataclass(frozen=True)
class SessionCompletedPayload(EventPayloadProtocol):
    """
    Payload for a session_completed HubEvent.

    Written directly to the persistence backend after domain Purposes have
    cleared (or after the SESSION_CLOSING timeout). Never multicast. This
    is the final record in every event log.

    is_last_out is always True in v0 — it marks that this is the definitive
    closing record for the session. Reserved for future multi-hub scenarios
    where multiple closers might race.
    """

    is_last_out: bool = True

    def as_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict for the event log."""
        return {
            "_schema": "session_completed",
            "_v": 1,
            "is_last_out": self.is_last_out,
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
