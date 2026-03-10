"""Purpose-originated event definitions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from ..protocols import EventPayloadProtocol

# DeltaProposalPayload moved to hub_events.py in v0.20.
# Import it from there (or from events/__init__.py) rather than here.
from .hub_events import (  # noqa: F401 re-export
    DeltaProposalPayload as DeltaProposalPayload,
)


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
    PURPOSE_COMPLETED = "purpose_completed"
    CTO_CLOSE_REQUEST = "cto_close_request"


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
