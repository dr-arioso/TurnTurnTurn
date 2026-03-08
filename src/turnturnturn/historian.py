"""Temporary hub-owned persistence seam for event and CTO history."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from .cto import CTO
from .events.hub_events import HubEvent
from .protocols import PurposeEventProtocol


def _event_type_value(value: object) -> str:
    """Return the canonical wire value for an event type enum/string."""
    return str(getattr(value, "value", value))


def _uuid_str(value: UUID | None) -> str | None:
    """Render UUIDs as strings for JSON-safe records."""
    return str(value) if value is not None else None


class HistorianProtocol(Protocol):
    """Write-only persistence sink for temporary hub-owned history capture."""

    async def record_hub_event(self, event: HubEvent) -> None: ...
    async def record_purpose_event(self, event: PurposeEventProtocol) -> None: ...
    async def record_cto_snapshot(self, cto: CTO) -> None: ...


@dataclass
class InMemoryHistorian:
    """In-memory historian useful for tests and inspection."""

    events: list[dict[str, Any]] = field(default_factory=list)
    cto_snapshots: list[dict[str, Any]] = field(default_factory=list)

    async def record_hub_event(self, event: HubEvent) -> None:
        self.events.append(hub_event_record(event))

    async def record_purpose_event(self, event: PurposeEventProtocol) -> None:
        self.events.append(purpose_event_record(event))

    async def record_cto_snapshot(self, cto: CTO) -> None:
        self.cto_snapshots.append(cto_snapshot_record(cto))


@dataclass
class JsonlHistorian:
    """Append-only JSONL historian for temporary file-backed persistence."""

    events_path: Path
    cto_snapshots_path: Path

    async def record_hub_event(self, event: HubEvent) -> None:
        self._append_jsonl(self.events_path, hub_event_record(event))

    async def record_purpose_event(self, event: PurposeEventProtocol) -> None:
        self._append_jsonl(self.events_path, purpose_event_record(event))

    async def record_cto_snapshot(self, cto: CTO) -> None:
        self._append_jsonl(self.cto_snapshots_path, cto_snapshot_record(cto))

    @staticmethod
    def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")


def hub_event_record(event: HubEvent) -> dict[str, Any]:
    """Serialize a hub-authored event into a persistence record."""
    return {
        "record_type": "hub_event",
        "event_type": _event_type_value(event.event_type),
        "event_id": str(event.event_id),
        "created_at_ms": event.created_at_ms,
        "session_id": _uuid_str(event.session_id),
        "turn_id": _uuid_str(event.turn_id),
        "payload": event.payload.as_dict(),
    }


def purpose_event_record(event: PurposeEventProtocol) -> dict[str, Any]:
    """Serialize an accepted Purpose-originated event into a record."""
    return {
        "record_type": "purpose_event",
        "event_type": _event_type_value(event.event_type),
        "event_id": str(event.event_id),
        "created_at_ms": event.created_at_ms,
        "purpose_id": str(event.purpose_id),
        "purpose_name": event.purpose_name,
        "payload": event.payload.as_dict(),
    }


def cto_snapshot_record(cto: CTO) -> dict[str, Any]:
    """Serialize canonical CTO state into a persistence snapshot record."""
    return {
        "record_type": "cto_snapshot",
        "turn_id": str(cto.turn_id),
        "session_id": str(cto.session_id),
        "created_at_ms": cto.created_at_ms,
        "content_profile": cto.content_profile,
        "content": cto.content,
        "observations": cto.observations,
        "last_event_id": _uuid_str(cto.last_event_id),
    }
