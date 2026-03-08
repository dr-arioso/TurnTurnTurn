"""
Test utilities for the TTT test suite.

These are test-only helpers — not part of the public TTT API. Nothing in
this module should be imported by production code.

InMemoryEventLog is a simple list accumulator for event-log assertions in
tests. It is not a PersistencePurpose and does not satisfy
CTOPersistencePurposeProtocol — it is a raw structural double for tests
that need to inspect serialized event records.

The serialization functions (hub_event_record, purpose_event_record,
cto_snapshot_record) are re-exported from
turnturnturn._event_serialization for convenience.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from turnturnturn._event_serialization import (  # noqa: F401 — re-exported
    cto_snapshot_record,
    hub_event_record,
    purpose_event_record,
)
from turnturnturn.cto import CTO
from turnturnturn.events.hub_events import HubEvent
from turnturnturn.protocols import PurposeEventProtocol


@dataclass
class InMemoryEventLog:
    """
    Simple list accumulator for serialized event and snapshot records.

    Used in tests that need to assert on the shape of the persistence
    record stream without instantiating a full PersistencePurpose. Not
    a Purpose, not a PersistencePurpose — it is a structural double.

    Append hub events, purpose events, and CTO snapshots by calling the
    corresponding methods. Inspect via .events and .cto_snapshots.
    """

    events: list[dict[str, Any]] = field(default_factory=list)
    cto_snapshots: list[dict[str, Any]] = field(default_factory=list)

    def append_hub_event(self, event: HubEvent) -> None:
        """Serialize and append a hub-authored event record."""
        self.events.append(hub_event_record(event))

    def append_purpose_event(self, event: PurposeEventProtocol) -> None:
        """Serialize and append an accepted Purpose-originated event record."""
        self.events.append(purpose_event_record(event))

    def append_cto_snapshot(self, cto: CTO) -> None:
        """Serialize and append a CTO snapshot record."""
        self.cto_snapshots.append(cto_snapshot_record(cto))

    def event_types(self) -> list[str]:
        """Return event_type values in order — convenient for sequence assertions."""
        return [e["event_type"] for e in self.events]
