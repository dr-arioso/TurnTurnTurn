"""
Persistence Purpose base class and in-memory implementation for TTT.

This module defines the two-tier hierarchy for event persistence:

  PersistencePurpose (abstract BasePurpose subclass)
      ↓
  Concrete backends (e.g. InMemoryPersistencePurpose, future JsonlPersistencePurpose)

PersistencePurpose implements _handle_event() by calling write_event() —
subclasses implement storage only, not routing. This keeps the Purpose
dispatch contract (take_turn → _handle_event) intact while giving backends
a clean single-method interface.

write_event() contract:
  - Must await completion before returning. The hub calls write_event()
    synchronously before delivering any event to other registered Purposes
    (enforced in Commit 6). Fire-and-forget implementations break the
    data integrity guarantee.
  - Must be idempotent on event_id. The hub may deliver the same event
    more than once during failover and reconciliation. Backends must handle
    duplicate event_ids without data corruption — last-write-wins on
    event_id is acceptable; double-appending is not.

is_durable contract:
  - Return True only if write_event() persists events beyond process
    termination (e.g. disk, database, external service). This property
    protects irreplaceable provenance data — a False value causes
    TTT.start() to emit UserWarning so operators know the log is ephemeral.
  - InMemoryPersistencePurpose.is_durable = False. It is the canonical
    development and test backend.

CTOPersistencePurposeProtocol is the runtime-checkable protocol that
TTT.start() will require (Commit 5). PersistencePurpose satisfies it by
construction; raw implementations of the protocol are also accepted.
"""

from __future__ import annotations

import abc
import importlib.metadata
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from ._event_serialization import hub_event_record
from .base_purpose import BasePurpose
from .events import (
    SessionCompletedEvent,
    SessionCompletedPayload,
    SessionStartedEvent,
    SessionStartedPayload,
)
from .events.hub_events import HubEvent, HubEventType
from .protocols import (  # noqa: F401 — re-exported
    CTOPersistencePurposeProtocol,
    EventProtocol,
    PurposeEventProtocol,
)


class PersistencePurpose(BasePurpose, abc.ABC):
    """
    Abstract base class for TTT persistence backends.

    Subclasses implement write_event() for storage. Routing and dispatch
    are handled by BasePurpose.take_turn() → _handle_event() → write_event().
    Do not override take_turn() or _handle_event().

    Subclass contract:
      - Declare is_durable as a class-level bool. True only if events
        survive process termination.
      - Implement write_event(event). Must be idempotent on event_id.
        Must await completion before returning.
      - Set name and id as for any BasePurpose subclass.

    See module docstring for the full write_event() and is_durable contracts.

    Architectural note:
      Persistence is a first-class mesh role, not just a side-channel sink.
      The long-term bootstrap model treats persistence as the first required
      participant on the mesh and the last to leave during shutdown.
    """

    @property
    @abc.abstractmethod
    def is_durable(self) -> bool:
        """
        Whether write_event() persists events beyond process termination.

        Return True only if the backend actually survives process exit.
        TTT.start() emits UserWarning when is_durable=False so operators
        know the event log is ephemeral.
        """

    async def _handle_event(self, event: HubEvent) -> None:
        """
        Receive a validated HubEvent and delegate to write_event().

        Called by BasePurpose.take_turn() after route credential validation.
        Do not override — implement write_event() instead.
        """
        await self.write_event(event)
        if (
            event.event_type == HubEventType.SESSION_CLOSE_PENDING
            and event.session_id is not None
        ):
            session_code = None
            payload_dict = event.payload.as_dict()
            if isinstance(payload_dict, dict):
                session_code = payload_dict.get("session_code")
            await self.complete_session_closing(str(event.session_id))
            await self.emit_session_completed(
                session_id=str(event.session_id),
                session_code=session_code if isinstance(session_code, str) else None,
            )

    async def _submit_purpose_event(self, event: PurposeEventProtocol) -> UUID | None:
        """
        Persist this Purpose's self-authored event before handing it to the hub.

        Persistence Purposes are responsible for persisting the events they
        emit. The hub still authenticates, orders, and reacts to the event,
        but it must not route the same event back into persistence a second
        time.
        """
        await self.write_event(event)
        return await self.hub.take_turn(event)

    @abc.abstractmethod
    async def write_event(self, event: EventProtocol) -> None:
        """
        Persist an accepted mesh event to the backend storage.

        Must await completion before returning — the hub relies on this
        for its persistence-before-dispatch guarantee. Must be idempotent
        on event.event_id — duplicate delivery must not corrupt the log.

        Args:
            event: The accepted EventProtocol to persist. Hub-authored and
                accepted Purpose-authored events are both valid here. Serialize
                via the canonical helpers in ``turnturnturn._event_serialization``.
        """

    async def emit_session_started(self, *, strict_profiles: bool) -> None:
        """
        Emit session_started for this persistence purpose if it is durable.

        Only durable persistence backends are permitted to author the durable
        session lifecycle facts.
        """
        if not self.is_durable:
            return
        try:
            ttt_version = importlib.metadata.version("turnturnturn")
        except importlib.metadata.PackageNotFoundError:
            ttt_version = "unknown"
        now_ms = int(time.time() * 1000)
        await self._submit_purpose_event(
            SessionStartedEvent(
                purpose_id=self.id,
                purpose_name=self.name,
                hub_token=self.token,
                payload=SessionStartedPayload(
                    hub_id=str(self.hub.hub_id),
                    ttt_version=ttt_version,
                    persister_name=self.name,
                    persister_id=str(self.id),
                    persister_is_durable=self.is_durable,
                    strict_profiles=strict_profiles,
                    created_at_ms=now_ms,
                ),
            )
        )

    async def emit_session_completed(
        self,
        *,
        session_id: str,
        session_code: str | None = None,
    ) -> None:
        """Emit session_completed for a closed session if this persister is durable."""
        if not self.is_durable:
            return
        await self._submit_purpose_event(
            SessionCompletedEvent(
                purpose_id=self.id,
                purpose_name=self.name,
                hub_token=self.token,
                session_id=UUID(session_id),
                payload=SessionCompletedPayload(
                    is_last_out=True,
                    session_code=session_code,
                ),
            )
        )


@dataclass
class InMemoryPersistencePurpose(PersistencePurpose):
    """
    In-memory persistence backend for development and testing.

    Stores serialized event records in a plain list. is_durable = False —
    TTT.start() will emit UserWarning when this backend is registered.

    This is the canonical test double and development backend. It is not
    suitable for production use where provenance must survive process
    termination.

    Attributes:
        events: Ordered list of serialized event records. Each entry is
            the dict produced by hub_event_record(). Inspect directly
            in tests for event-log assertions.
    """

    name: str = "in_memory_persistence"
    events: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Initialise BasePurpose state and assign a unique instance id."""
        super().__init__()
        self.id = uuid4()

    @property
    def is_durable(self) -> bool:
        """Always False — in-memory storage does not survive process termination."""
        return False

    async def write_event(self, event: EventProtocol) -> None:
        """
        Serialize and append the event to the in-memory events list.

        Idempotent on event_id: if an event with the same event_id is
        already present, the duplicate is silently dropped.
        """
        from ._event_serialization import hub_event_record, purpose_event_record

        event_id = str(event.event_id)
        if any(e.get("event_id") == event_id for e in self.events):
            return
        if isinstance(event, HubEvent):
            self.events.append(hub_event_record(event))
        else:
            self.events.append(purpose_event_record(event))
