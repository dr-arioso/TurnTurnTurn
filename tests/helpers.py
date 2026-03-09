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
from uuid import UUID

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


def make_start_turn_kwargs(
    submitter_token: str,
    session_id: UUID,
    content_profile: str = "conversation",
    content: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Build keyword arguments for hub.start_turn() with the current signature.

    Convenience helper for tests that construct start_turn() calls directly
    rather than using the submitter fixture. Centralises the positional/keyword
    argument layout so tests don't need to track the exact signature.

    Args:
        submitter_token: hub_token of the registered Purpose submitting the turn.
        session_id: Session UUID to associate with the turn.
        content_profile: Profile identifier string. Defaults to "conversation".
        content: Profile-conformant content dict. Defaults to minimal valid
            conversation content if not provided.

    Returns:
        A dict suitable for unpacking into hub.start_turn(**kwargs).
    """
    if content is None:
        content = {"speaker": {"id": "usr_test"}, "text": "hello"}
    return {
        "content_profile": content_profile,
        "content": content,
        "hub_token": submitter_token,
        "session_id": session_id,
    }
