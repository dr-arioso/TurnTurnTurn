"""
Canonical wire-format serialization for TTT events and CTO snapshots.

These functions define the on-disk and on-wire record schema for
persistence backends. Their output is what Archivist backends and other
persistence sinks write, and what replay tooling reads. Schema stability
matters: downstream consumers — log analysis, replay, regression
testing — depend on the shape of these dicts being consistent across TTT
versions.

Schema versioning is the responsibility of the producing code
(payload.as_dict() methods carry _schema and _v fields). The envelope
fields produced here (record_type, event_type, event_id,
created_at_ms, session_id, turn_id) are stable from v0.19.

These functions are private to the turnturnturn package. They are used
by core persistence code and may be imported by tests/helpers.py for
assertion utilities. They are not part of the public API surface.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from .cto import CTO
from .events.hub_events import HubEvent
from .protocols import PurposeEventProtocol


def _event_type_value(value: object) -> str:
    """
    Return the canonical wire string for an event type enum or plain string.

    Enum members carry their wire value in `.value`; plain strings pass
    through unchanged. Used to produce consistent event_type fields
    regardless of whether the caller holds an enum member or a string.
    """
    return str(getattr(value, "value", value))


def _uuid_str(value: UUID | None) -> str | None:
    """
    Render a UUID as a string, or return None if the value is None.

    Used throughout serialization to produce JSON-safe UUID fields while
    preserving the distinction between a present UUID and an absent one.
    """
    return str(value) if value is not None else None


def hub_event_record(event: HubEvent) -> dict[str, Any]:
    """
    Serialize a hub-authored HubEvent into a persistence record dict.

    Produces the canonical envelope for hub events in the event log.
    The payload is serialized via event.payload.as_dict(), which carries
    _schema and _v for schema-version-aware deserialization.

    Record shape (stable from v0.19):
        record_type  : "hub_event"
        event_type   : wire string (e.g. "cto_started", "delta_merged")
        event_id     : UUID string
        created_at_ms: int (Unix ms)
        session_id   : UUID string or None
        turn_id      : UUID string or None
        payload      : dict from event.payload.as_dict()

    Args:
        event: The hub-authored HubEvent to serialize.

    Returns:
        A JSON-safe dict suitable for appending to an event log.
    """
    return {
        "record_type": "hub_event",
        "event_type": _event_type_value(event.event_type),
        "event_id": str(event.event_id),
        "created_at_ms": event.created_at_ms,
        "session_id": _uuid_str(event.session_id),
        "turn_id": _uuid_str(event.turn_id),
        "payload": event.payload.as_dict(),
    }


def purpose_event_record(event: PurposeEventProtocol) -> dict[str, Any]:
    """
    Serialize an accepted Purpose-originated event into a persistence record.

    Only events that have passed hub ingress validation should be passed
    here — the record does not capture rejection outcomes.

    Record shape (stable from v0.19):
        record_type  : "purpose_event"
        event_type   : wire string (e.g. "propose_delta")
        event_id     : UUID string
        created_at_ms: int (Unix ms)
        purpose_id   : UUID string
        purpose_name : str
        payload      : dict from event.payload.as_dict()

    Args:
        event: An accepted PurposeEventProtocol implementor.

    Returns:
        A JSON-safe dict suitable for appending to an event log.
    """
    return {
        "record_type": "purpose_event",
        "event_type": _event_type_value(event.event_type),
        "event_id": str(event.event_id),
        "created_at_ms": event.created_at_ms,
        "session_id": _uuid_str(getattr(event, "session_id", None)),
        "turn_id": _uuid_str(getattr(event, "turn_id", None)),
        "purpose_id": str(event.purpose_id),
        "purpose_name": event.purpose_name,
        "payload": event.payload.as_dict(),
    }


def cto_snapshot_record(cto: CTO) -> dict[str, Any]:
    """
    Serialize canonical CTO state into a persistence snapshot record.

    CTO snapshots capture the full canonical state at a point in time.
    They are written after every cto_started and delta_merged event so
    that the log contains both the event (what happened) and the
    resulting state (what it produced).

    Record shape (stable from v0.19):
        record_type    : "cto_snapshot"
        turn_id        : UUID string
        session_id     : UUID string
        created_at_ms  : int (Unix ms)
        content_profile: dict {"id": str, "version": int}
        content        : dict (profile-conformant content)
        observations   : dict {purpose_name: [obs, ...]}
        last_event_id  : UUID string or None

    Args:
        cto: The canonical CTO to snapshot.

    Returns:
        A JSON-safe dict suitable for appending to a snapshot log.
        Callers are responsible for ensuring observation values are
        JSON-safe — the hub enforces append-only list semantics but
        does not constrain value types beyond that.
    """
    return {
        "record_type": "cto_snapshot",
        "turn_id": str(cto.turn_id),
        "session_id": str(cto.session_id),
        "created_at_ms": cto.created_at_ms,
        "content_profile": cto.content_profile,
        "content": cto.content,
        "observations": cto.observations,
        "last_event_id": _uuid_str(cto.last_event_id),
    }
