"""Purpose-originated event definitions."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from ..delta import Delta
from ..protocols import EventPayloadProtocol
from .hub_events import HubEventType


@dataclass(frozen=True)
class DeltaProposalPayload(EventPayloadProtocol):
    """
    Payload for a Purpose-originated delta proposal.

    This is a proposal, not a hub-authored fact. The hub validates the
    submitting Purpose and decides whether and how the proposal becomes
    canonical state.
    """

    delta: Delta

    def as_dict(self) -> dict[str, object]:
        return {"delta": self.delta.to_dict()}


@dataclass(frozen=True)
class DeltaProposalEvent:
    """
    Purpose-originated ingress event used to propose a Delta to the hub.

    The hub validates purpose_id, purpose_name, and hub_token against the
    registration resolved from hub_token before routing the event.
    """

    event_type: HubEventType
    event_id: UUID
    created_at_ms: int
    purpose_id: UUID
    purpose_name: str
    hub_token: str
    payload: DeltaProposalPayload
