"""Purpose-originated event definitions."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from ..protocols import EventPayloadProtocol

# DeltaProposalPayload moved to hub_events.py in v0.20.
# Import it from there (or from events/__init__.py) rather than here.
from .hub_events import (  # noqa: F401 re-export
    DeltaProposalPayload as DeltaProposalPayload,
)
from .hub_events import PurposeStartedPayload as PurposeStartedPayload
from .hub_events import SessionCompletedPayload as SessionCompletedPayload
from .hub_events import SessionStartedPayload as SessionStartedPayload


def _now_ms() -> int:
    return int(time.time() * 1000)


class PurposeEventType(str, Enum):
    """
    Purpose-authored event types submitted to the hub via hub.take_turn().

    These are proposals or lifecycle signals from a registered Purpose, not
    hub-authored facts.

    CTOCloseRequest signals that the originating Purpose considers a CTO's
    processing complete from its own perspective. The hub stub currently
    accepts and ignores it; the DAG layer will implement quiescence logic.
    """

    DELTA_PROPOSAL = "delta_proposal"
    PURPOSE_STARTED = "purpose_started"
    SESSION_STARTED = "session_started"
    CTO_REQUEST = "cto_request"
    CTO_IMPORTED = "cto_imported"
    END_SESSION = "end_session"
    PURPOSE_COMPLETED = "purpose_completed"
    SESSION_COMPLETED = "session_completed"
    CTO_CLOSE_REQUEST = "cto_close_request"


@dataclass(frozen=True)
class EndSessionPayload(EventPayloadProtocol):
    """Payload for a Purpose-originated request to end a session."""

    session_id: str
    reason: str = "normal"

    def as_dict(self) -> dict[str, object]:
        return {
            "_schema": "end_session",
            "_v": 1,
            "session_id": self.session_id,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class CTORequestPayload(EventPayloadProtocol):
    """Payload for a Purpose-originated request to import a CTO JSON document."""

    session_id: str
    source_kind: str
    source_locator: str
    requested_by_purpose_id: str
    requested_by_purpose_name: str
    session_code: str | None = None
    request_id: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "_schema": "cto_request",
            "_v": 1,
            "session_id": self.session_id,
            "source_kind": self.source_kind,
            "source_locator": self.source_locator,
            "requested_by_purpose_id": self.requested_by_purpose_id,
            "requested_by_purpose_name": self.requested_by_purpose_name,
            "session_code": self.session_code,
            "request_id": self.request_id,
        }


@dataclass(frozen=True)
class CTOImportedPayload(EventPayloadProtocol):
    """Payload for a persistence-authored imported CTO awaiting hub adoption."""

    session_id: str
    source_kind: str
    source_locator: str
    source_content_hash: str
    requested_by_purpose_id: str
    requested_by_purpose_name: str
    cto_json: dict[str, Any]
    session_code: str | None = None
    request_id: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "_schema": "cto_imported",
            "_v": 1,
            "session_id": self.session_id,
            "source_kind": self.source_kind,
            "source_locator": self.source_locator,
            "source_content_hash": self.source_content_hash,
            "requested_by_purpose_id": self.requested_by_purpose_id,
            "requested_by_purpose_name": self.requested_by_purpose_name,
            "session_code": self.session_code,
            "request_id": self.request_id,
            "cto_json": self.cto_json,
        }


@dataclass(frozen=True)
class PurposeCompletedPayload(EventPayloadProtocol):
    """Payload for a Purpose-originated acknowledgement of session closing."""

    session_id: str
    reason: str = "normal"

    def as_dict(self) -> dict[str, object]:
        return {
            "_schema": "purpose_completed",
            "_v": 1,
            "session_id": self.session_id,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class EndSessionEvent:
    """Purpose-authored event requesting that the hub begin session shutdown."""

    purpose_id: UUID
    purpose_name: str
    hub_token: str
    payload: EndSessionPayload
    event_type: PurposeEventType = field(
        default=PurposeEventType.END_SESSION, init=False
    )
    event_id: UUID = field(default_factory=uuid4, init=False)
    created_at_ms: int = field(default_factory=_now_ms, init=False)


@dataclass(frozen=True)
class CTORequestEvent:
    """Purpose-authored event requesting that persistence import a CTO JSON document."""

    purpose_id: UUID
    purpose_name: str
    hub_token: str
    session_id: UUID
    payload: CTORequestPayload
    event_type: PurposeEventType = field(
        default=PurposeEventType.CTO_REQUEST, init=False
    )
    event_id: UUID = field(default_factory=uuid4, init=False)
    created_at_ms: int = field(default_factory=_now_ms, init=False)


@dataclass(frozen=True)
class CTOImportedEvent:
    """Persistence-authored event carrying a normalized imported CTO document."""

    purpose_id: UUID
    purpose_name: str
    hub_token: str
    session_id: UUID
    payload: CTOImportedPayload
    event_type: PurposeEventType = field(
        default=PurposeEventType.CTO_IMPORTED, init=False
    )
    event_id: UUID = field(default_factory=uuid4, init=False)
    created_at_ms: int = field(default_factory=_now_ms, init=False)


@dataclass(frozen=True)
class PurposeStartedEvent:
    """Purpose-authored provenance event announcing successful mesh admission."""

    purpose_id: UUID
    purpose_name: str
    hub_token: str
    payload: PurposeStartedPayload
    event_type: PurposeEventType = field(
        default=PurposeEventType.PURPOSE_STARTED, init=False
    )
    event_id: UUID = field(default_factory=uuid4, init=False)
    created_at_ms: int = field(default_factory=_now_ms, init=False)


@dataclass(frozen=True)
class SessionStartedEvent:
    """Durable persistence-authored provenance event announcing session bootstrap."""

    purpose_id: UUID
    purpose_name: str
    hub_token: str
    payload: SessionStartedPayload
    event_type: PurposeEventType = field(
        default=PurposeEventType.SESSION_STARTED, init=False
    )
    event_id: UUID = field(default_factory=uuid4, init=False)
    created_at_ms: int = field(default_factory=_now_ms, init=False)


@dataclass(frozen=True)
class PurposeCompletedEvent:
    """Purpose-authored event acknowledging that local shutdown work is complete."""

    purpose_id: UUID
    purpose_name: str
    hub_token: str
    payload: PurposeCompletedPayload
    event_type: PurposeEventType = field(
        default=PurposeEventType.PURPOSE_COMPLETED, init=False
    )
    event_id: UUID = field(default_factory=uuid4, init=False)
    created_at_ms: int = field(default_factory=_now_ms, init=False)


@dataclass(frozen=True)
class SessionCompletedEvent:
    """Durable persistence-authored final session completion event."""

    purpose_id: UUID
    purpose_name: str
    hub_token: str
    session_id: UUID
    payload: SessionCompletedPayload
    event_type: PurposeEventType = field(
        default=PurposeEventType.SESSION_COMPLETED, init=False
    )
    event_id: UUID = field(default_factory=uuid4, init=False)
    created_at_ms: int = field(default_factory=_now_ms, init=False)


@dataclass(frozen=True)
class CTOCloseRequestPayload(EventPayloadProtocol):
    """
    Payload for a Purpose-originated CTOCloseRequest event.

    Carries only turn_id — the Purpose is signalling satisfaction with a
    specific CTO, not submitting data. The hub stub currently accepts this
    event and takes no action; the DAG layer will use it to drive
    quiescence detection and CTO_COMPLETED emission.
    """

    turn_id: str  # UUID as string

    def as_dict(self) -> dict[str, object]:
        """Serialize to a JSON-safe dict for the event log."""
        return {
            "_schema": "cto_close_request",
            "_v": 1,
            "turn_id": self.turn_id,
        }


@dataclass(frozen=True)
class CTOCloseRequestEvent:
    """
    Purpose-authored event signalling that the originating Purpose considers
    a CTO's processing complete.

    Submitted via hub.take_turn(). The hub validates purpose_id,
    purpose_name, and hub_token against the registration resolved from
    hub_token before routing. In v0, the hub accepts and ignores this
    event (no-op stub). The DAG layer will implement quiescence logic.
    """

    event_type: PurposeEventType
    event_id: UUID
    created_at_ms: int
    purpose_id: UUID
    purpose_name: str
    hub_token: str
    payload: CTOCloseRequestPayload


@dataclass(frozen=True)
class DeltaProposalEvent:
    """
    Purpose-authored event used to propose a Delta to the hub.

    The hub validates purpose_id, purpose_name, and hub_token against the
    registration resolved from hub_token before routing the event.
    """

    event_type: PurposeEventType
    event_id: UUID
    created_at_ms: int
    purpose_id: UUID
    purpose_name: str
    hub_token: str
    payload: DeltaProposalPayload
