"""Public event and payload surface for hub and Purpose routing."""

from .hub_events import (
    SessionStartPayload,  # deprecated alias for SessionStartedPayload; remove in v0.21
)
from .hub_events import (
    CTOCompletedPayload,
    CTOStartedPayload,
    DeltaMergedPayload,
    DeltaRejectedPayload,
    EmptyPayload,
    HubEvent,
    HubEventType,
    ProposeDeltaPayload,
    PurposeStartedPayload,
    SessionClosePendingPayload,
    SessionClosingPayload,
    SessionCompletedPayload,
    SessionStartedPayload,
)
from .purpose_events import (
    CTOImported,
    CTOImportedPayload,
    ProposeDelta,
    PurposeCompleted,
    PurposeCompletedPayload,
    PurposeEventType,
    PurposeStarted,
    RequestCTO,
    RequestCTOClose,
    RequestCTOClosePayload,
    RequestCTOPayload,
    RequestSessionEnd,
    RequestSessionEndPayload,
    SessionCompleted,
    SessionStarted,
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
    "ProposeDeltaPayload",
    # Purpose lifecycle payloads
    "PurposeStartedPayload",
    # Session lifecycle payloads
    "SessionStartedPayload",
    "SessionStartPayload",  # deprecated alias; remove in v0.21
    "SessionClosingPayload",
    "SessionClosePendingPayload",
    "SessionCompletedPayload",
    # Utility
    "EmptyPayload",
    # Purpose-originated events
    "ProposeDelta",
    "RequestSessionEnd",
    "RequestSessionEndPayload",
    "RequestCTO",
    "RequestCTOPayload",
    "CTOImported",
    "CTOImportedPayload",
    "RequestCTOClose",
    "RequestCTOClosePayload",
    "PurposeStarted",
    "PurposeCompleted",
    "PurposeCompletedPayload",
    "SessionStarted",
    "SessionCompleted",
    "PurposeEventType",
]
