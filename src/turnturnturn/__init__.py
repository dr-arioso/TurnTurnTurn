"""Public package surface for TurnTurnTurn."""

from .base_purpose import BasePurpose
from .cto import CTO
from .delta import Delta
from .errors import (
    InvalidDownlinkSignatureError,
    PersistenceFailureError,
    TTTError,
    UnauthorizedDispatchError,
    UnboundPurposeError,
    UnknownEventTypeError,
)
from .events import (
    CTOCreatedPayload,  # deprecated alias for CTOStartedPayload; remove in v0.21
)
from .events import (
    SessionStartPayload,  # deprecated alias for SessionStartedPayload; remove in v0.21
)
from .events import (
    CTOCloseRequestEvent,
    CTOCloseRequestPayload,
    CTOCompletedPayload,
    CTOStartedPayload,
    DeltaMergedPayload,
    DeltaProposalEvent,
    DeltaProposalPayload,
    DeltaRejectedPayload,
    EmptyPayload,
    HubEvent,
    HubEventType,
    PurposeEventType,
    PurposeStartedPayload,
    SessionClosingPayload,
    SessionCompletedPayload,
    SessionStartedPayload,
)
from .hub import TTT
from .persistence import InMemoryPersistencePurpose, PersistencePurpose
from .protocols import (
    CTOPersistencePurposeProtocol,
    EventPayloadProtocol,
    EventProtocol,
    PurposeEventProtocol,
)

__all__ = [
    "BasePurpose",
    "CTO",
    "Delta",
    "TTT",
    # Errors
    "TTTError",
    "InvalidDownlinkSignatureError",
    "PersistenceFailureError",
    "UnauthorizedDispatchError",
    "UnboundPurposeError",
    "UnknownEventTypeError",
    # Protocols
    "CTOPersistencePurposeProtocol",
    "EventPayloadProtocol",
    "EventProtocol",
    "PurposeEventProtocol",
    # Persistence
    "InMemoryPersistencePurpose",
    "PersistencePurpose",
    # Hub event envelope
    "HubEvent",
    "HubEventType",
    # CTO lifecycle payloads
    "CTOStartedPayload",
    "CTOCreatedPayload",  # deprecated alias; remove in v0.21
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
