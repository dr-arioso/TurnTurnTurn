"""Public event and payload surface for hub and Purpose routing."""

from .hub_events import (
    SessionStartPayload,  # deprecated alias for SessionStartedPayload; remove in v0.21
)
from .hub_events import (
    CTOCompletedPayload,
    CTOStartedPayload,
    DeltaMergedPayload,
    DeltaProposalPayload,
    DeltaRejectedPayload,
    EmptyPayload,
    HubEvent,
    HubEventType,
    PurposeStartedPayload,
    SessionClosingPayload,
    SessionCompletedPayload,
    SessionStartedPayload,
)
from .purpose_events import (
    CTOCloseRequestEvent,
    CTOCloseRequestPayload,
    DeltaProposalEvent,
    PurposeEventType,
)

__all__ = [
    # Hub event envelope
    "HubEvent",
    "HubEventType",
    # CTO lifecycle payloads
    "CTOStartedPayload",
    "CTOCompletedPayload",
    # Delta lifecycle payloads
    "DeltaMergedPayload",
    "DeltaRejectedPayload",
    "DeltaProposalPayload",
    # Purpose lifecycle payloads
    "PurposeStartedPayload",
    # Session lifecycle payloads
    "SessionStartedPayload",
    "SessionStartPayload",  # deprecated alias; remove in v0.21
    "SessionClosingPayload",
    "SessionCompletedPayload",
    # Utility
    "EmptyPayload",
    # Purpose-originated events
    "DeltaProposalEvent",
    "CTOCloseRequestEvent",
    "CTOCloseRequestPayload",
    "PurposeEventType",
]
