"""Public package surface for TurnTurnTurn."""

from .archivist import (
    Archivist,
    ArchivistBackendConfig,
    ArchivistBackendProtocol,
    JsonlArchivistBackend,
    JsonlArchivistBackendConfig,
    SessionDocumentArchivistBackend,
    SessionDocumentArchivistBackendConfig,
)
from .base_purpose import BasePurpose, SessionOwnerPurpose
from .cto import CTO
from .cto_json import (
    CTO_JSON_SCHEMA,
    CTO_JSON_VERSION,
    TTT_PROVENANCE_NAMESPACE,
    cto_json_document,
    load_cto_json_document,
    normalize_cto_json_document,
)
from .delta import Delta
from .errors import (
    HubClosedError,
    InvalidDownlinkSignatureError,
    PersistenceFailureError,
    TTTError,
    UnauthorizedDispatchError,
    UnboundPurposeError,
    UnknownEventTypeError,
)
from .events import (
    CTOCloseRequestEvent,
    CTOCloseRequestPayload,
    CTOCompletedPayload,
    CTOImportedEvent,
    CTOImportedPayload,
    CTORequestEvent,
    CTORequestPayload,
    CTOStartedPayload,
    DeltaMergedPayload,
    DeltaProposalEvent,
    DeltaProposalPayload,
    DeltaRejectedPayload,
    EmptyPayload,
    HubEvent,
    HubEventType,
    PurposeEventType,
    PurposeStartedEvent,
    PurposeStartedPayload,
    SessionClosingPayload,
    SessionCompletedEvent,
    SessionCompletedPayload,
    SessionStartedEvent,
    SessionStartedPayload,
    SessionStartPayload,
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
    "SessionOwnerPurpose",
    "CTO",
    "CTO_JSON_SCHEMA",
    "CTO_JSON_VERSION",
    "TTT_PROVENANCE_NAMESPACE",
    "cto_json_document",
    "load_cto_json_document",
    "normalize_cto_json_document",
    "Delta",
    "TTT",
    # Errors
    "TTTError",
    "HubClosedError",
    "InvalidDownlinkSignatureError",
    "PersistenceFailureError",
    "UnauthorizedDispatchError",
    "UnboundPurposeError",
    "UnknownEventTypeError",
    # Protocols
    "ArchivistBackendProtocol",
    "CTOPersistencePurposeProtocol",
    "EventPayloadProtocol",
    "EventProtocol",
    "PurposeEventProtocol",
    # Persistence
    "InMemoryPersistencePurpose",
    "PersistencePurpose",
    "ArchivistBackendConfig",
    "JsonlArchivistBackend",
    "JsonlArchivistBackendConfig",
    "Archivist",
    "SessionDocumentArchivistBackend",
    "SessionDocumentArchivistBackendConfig",
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
    "CTORequestEvent",
    "CTORequestPayload",
    "CTOImportedEvent",
    "CTOImportedPayload",
    "CTOCloseRequestEvent",
    "CTOCloseRequestPayload",
    "PurposeStartedEvent",
    "SessionStartedEvent",
    "SessionCompletedEvent",
    "PurposeEventType",
]
