"""Purpose-originated event definitions."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from ..protocols import EventPayloadProtocol

# ProposeDeltaPayload moved to hub_events.py in v0.20.
# Import it from there (or from events/__init__.py) rather than here.
from .hub_events import (  # noqa: F401 re-export
    ProposeDeltaPayload as ProposeDeltaPayload,
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

    RequestCTOClose signals that the originating Purpose considers a CTO's
    processing complete from its own perspective. The hub stub currently
    accepts and ignores it; the DAG layer will implement quiescence logic.
    """

    PROPOSE_DELTA = "propose_delta"
    PURPOSE_STARTED = "purpose_started"
    SESSION_STARTED = "session_started"
    REQUEST_CTO = "request_cto"
    CTO_IMPORTED = "cto_imported"
    REQUEST_SESSION_END = "request_session_end"
    PURPOSE_COMPLETED = "purpose_completed"
    SESSION_COMPLETED = "session_completed"
    REQUEST_CTO_CLOSE = "request_cto_close"


@dataclass(frozen=True)
class RequestSessionEndPayload(EventPayloadProtocol):
    """Payload for a Purpose-originated request to end a session."""

    session_id: str
    reason: str = "normal"

    def as_dict(self) -> dict[str, object]:
        return {
            "_schema": "request_session_end",
            "_v": 1,
            "session_id": self.session_id,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RequestCTOPayload(EventPayloadProtocol):
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
            "_schema": "request_cto",
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
class RequestSessionEnd:
    """Purpose-authored event requesting that the hub begin session shutdown."""

    purpose_id: UUID
    purpose_name: str
    hub_token: str
    payload: RequestSessionEndPayload
    event_type: PurposeEventType = field(
        default=PurposeEventType.REQUEST_SESSION_END, init=False
    )
    event_id: UUID = field(default_factory=uuid4, init=False)
    created_at_ms: int = field(default_factory=_now_ms, init=False)


@dataclass(frozen=True)
class RequestCTO:
    """Purpose-authored event requesting that persistence import a CTO JSON document."""

    purpose_id: UUID
    purpose_name: str
    hub_token: str
    session_id: UUID
    payload: RequestCTOPayload
    event_type: PurposeEventType = field(
        default=PurposeEventType.REQUEST_CTO, init=False
    )
    event_id: UUID = field(default_factory=uuid4, init=False)
    created_at_ms: int = field(default_factory=_now_ms, init=False)


@dataclass(frozen=True)
class CTOImported:
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
class PurposeStarted:
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
class SessionStarted:
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
class PurposeCompleted:
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
class SessionCompleted:
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
class RequestCTOClosePayload(EventPayloadProtocol):
    """
    Payload for a Purpose-originated RequestCTOClose event.

    Carries only turn_id — the Purpose is signalling satisfaction with a
    specific CTO, not submitting data. The hub stub currently accepts this
    event and takes no action; the DAG layer will use it to drive
    quiescence detection and CTO_COMPLETED emission.
    """

    turn_id: str  # UUID as string

    def as_dict(self) -> dict[str, object]:
        """Serialize to a JSON-safe dict for the event log."""
        return {
            "_schema": "request_cto_close",
            "_v": 1,
            "turn_id": self.turn_id,
        }


@dataclass(frozen=True)
class RequestCTOClose:
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
    payload: RequestCTOClosePayload


@dataclass(frozen=True)
class ProposeDelta:
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
    payload: ProposeDeltaPayload
