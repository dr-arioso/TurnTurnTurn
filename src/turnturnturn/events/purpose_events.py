"""Purpose-originated event definitions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from ..delta import Delta
from ..protocols import EventPayloadProtocol


class PurposeEventType(str, Enum):
    """
    Purpose-authored event types submitted to the hub.

    These are proposals or lifecycle signals from a registered Purpose, not
    hub-authored facts.
    """

    DELTA_PROPOSAL = "delta_proposal"
    PURPOSE_COMPLETED = "purpose_completed"


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
