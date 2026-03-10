"""Structural protocols for TTT participants and event envelopes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable
from uuid import UUID

if TYPE_CHECKING:
    from .events import HubEvent


@runtime_checkable
class EventPayloadProtocol(Protocol):
    """
    Serialization contract for event payload objects.

    All events carry a payload object rather than an ad-hoc dict so the hub
    can rely on a uniform serialization path for logging, persistence, and
    debugging.
    """

    def as_dict(self) -> dict[str, Any]: ...


@runtime_checkable
class EventProtocol(Protocol):
    """
    Minimal event envelope contract shared by hub-authored and
    Purpose-originated events.
    """

    event_type: str
    event_id: UUID
    created_at_ms: int
    payload: EventPayloadProtocol


@runtime_checkable
class PurposeEventProtocol(EventProtocol, Protocol):
    """
    Stricter envelope contract for Purpose-originated ingress events.

    These fields represent a claim of origin. The hub validates that the
    claimed sender matches the registration resolved from hub_token before
    routing the event.
    """

    purpose_id: UUID
    purpose_name: str
    hub_token: str


@runtime_checkable
class TurnTakerProtocol(Protocol):
    """
    A component that can receive hub-authored events.

    NOTE:
    - "TurnTaker" is a capability role (can participate in the event mesh).
    - "Purpose" is the agenda-bearing registered actor (see PurposeProtocol).
    """

    async def take_turn(self, event: HubEvent) -> None: ...


@runtime_checkable
class PurposeProtocol(TurnTakerProtocol, Protocol):
    """
    A registered agenda-bearing actor in the TTT mesh.

    Identification:
      - name: semantic kind ("ca", "embeddingizer", "socratic", ...)
      - id: per-instance UUID (multiple instances can share the same name)
      - token: hub-assigned ingress token, None until registered with a hub.

    BasePurpose is the recommended implementation base — it enforces that
    take_turn() rejects events whose routing credentials do not match the
    values assigned by the hub at registration.

    Raw PurposeProtocol implementors (e.g. simple test doubles) may still be
    registered, but because they do not participate in BasePurpose validation,
    they should be treated as test-only conveniences rather than production
    implementations.
    """

    name: str
    id: UUID
    token: str | None


@runtime_checkable
class CTOPersistencePurposeProtocol(PurposeProtocol, Protocol):
    """
    Runtime-checkable protocol for TTT persistence Purposes.

    Required by TTT.start() — the hub will not initialise without a
    registered instance satisfying this protocol. Defines the minimal
    contract that all persistence backends must satisfy.

    PersistencePurpose (persistence.py) satisfies this protocol by
    construction and is the recommended base class for backends.
    Raw implementations are accepted but must honour both contracts below.

    is_durable:
        Declares whether write_event() persists events beyond the current
        process. False is valid for development and test contexts;
        TTT.start() emits UserWarning when is_durable=False. Implementors
        must not return True unless the backend actually survives process
        termination — this property protects irreplaceable provenance data.

    write_event():
        Must await completion before returning. The hub calls write_event()
        before delivering any event to other registered Purposes (enforced
        in Commit 6 / _multicast rewrite). Idempotent on event_id —
        backends must handle duplicate delivery without data corruption.
    """

    is_durable: bool

    async def write_event(self, event: "HubEvent") -> None: ...
