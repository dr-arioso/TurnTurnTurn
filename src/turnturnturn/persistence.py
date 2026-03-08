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
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from ._event_serialization import hub_event_record
from .base_purpose import BasePurpose
from .events.hub_events import HubEvent
from .protocols import CTOPersistencePurposeProtocol  # noqa: F401 — re-exported


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

    @abc.abstractmethod
    async def write_event(self, event: HubEvent) -> None:
        """
        Persist a HubEvent to the backend storage.

        Must await completion before returning — the hub relies on this
        for its persistence-before-dispatch guarantee. Must be idempotent
        on event.event_id — duplicate delivery must not corrupt the log.

        Args:
            event: The HubEvent to persist. Serialize via
                turnturnturn._event_serialization.hub_event_record(event)
                for the canonical wire format, or use event.payload.as_dict()
                if only payload content is needed.
        """


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

    async def write_event(self, event: HubEvent) -> None:
        """
        Serialize and append the event to the in-memory events list.

        Idempotent on event_id: if an event with the same event_id is
        already present, the duplicate is silently dropped.
        """
        event_id = str(event.event_id)
        if any(e.get("event_id") == event_id for e in self.events):
            return
        self.events.append(hub_event_record(event))
