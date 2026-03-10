"""
Archivist — pluggable durable persistence for TTT event streams.

This module defines the backend protocol and configuration that Archivist
backends must satisfy. Concrete backends (JsonlArchivistBackend,
SessionDocumentArchivistBackend) and the Archivist PersistencePurpose
subclass are added in subsequent commits.

Architecture note:
  Archivist is a PersistencePurpose subclass. From the hub's perspective it
  is an opaque durable backend — it satisfies CTOPersistencePurposeProtocol
  and receives every event before any domain Purpose does.

  Internally, Archivist fans out to a list of pluggable backends. Each
  backend satisfies ArchivistBackendProtocol (a single async accept() method)
  and is paired with an ArchivistBackendConfig that declares which events and
  profiles it should receive.

  This separation means:
    - The hub knows nothing about JSONL files or session documents.
    - Backends know nothing about each other or about hub routing.
    - ArchivistBackendConfig is the only coupling point between them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from ._event_serialization import hub_event_record
from .events.hub_events import HubEvent, HubEventType

if TYPE_CHECKING:
    pass  # reserved for future type-only imports


@runtime_checkable
class ArchivistBackendProtocol(Protocol):
    """
    Protocol that all Archivist storage backends must satisfy.

    A backend is responsible for persisting or processing a single HubEvent.
    Filtering (by event type and content profile) is applied by Archivist
    before calling accept() — backends receive only events they have been
    configured to handle.

    Backends must be safe to call concurrently if multiple events are in
    flight, though in v0 the hub dispatches events sequentially.
    """

    async def accept(self, event: HubEvent) -> None:
        """
        Persist or process a single HubEvent.

        Called by Archivist after filter matching. Must await completion
        before returning — Archivist does not fire-and-forget. Implementations
        should be idempotent where possible, but unlike write_event() on
        InMemoryPersistencePurpose, deduplication is not required at this
        layer (the hub guarantees each event is delivered once).

        Args:
            event: The HubEvent to persist. The event has already passed
                Archivist's event_type and content_profile filters.
        """
        ...


@dataclass
class ArchivistBackendConfig:
    """
    Filter configuration for a single Archivist backend.

    Archivist evaluates these filters before calling backend.accept(). A
    backend's accept() is only called when both filters pass. Backends
    receive every event if neither filter is set.

    Subclass this to add backend-specific configuration fields (e.g. output
    path, serialization shape). The Archivist constructor accepts instances
    of any ArchivistBackendConfig subclass alongside their backend.

    Attributes:
        event_types: If set, only events whose event_type is in this set are
            forwarded to the backend. None means all event types are forwarded.
        content_profile: If set, only events whose CTO content profile id
            matches this string are forwarded. None means all profiles are
            forwarded. For events that are not CTO-scoped (e.g. session
            lifecycle events), the content_profile filter is not applied —
            those events always pass.
    """

    event_types: set[HubEventType] | None = field(default=None)
    content_profile: str | None = field(default=None)

    def matches(self, event: HubEvent) -> bool:
        """
        Return True if this event should be forwarded to the paired backend.

        Event type filter: if event_types is set, the event's type must be
        in the set. Session and purpose lifecycle events have no CTO scope,
        so content_profile filtering is skipped for them even if configured.

        Args:
            event: The HubEvent to evaluate.

        Returns:
            True if the event passes all configured filters.
        """
        if self.event_types is not None and event.event_type not in self.event_types:
            return False

        # Content profile filter only applies to CTO-scoped events.
        # Non-CTO events (session lifecycle, purpose lifecycle) are not
        # associated with a profile and always pass this filter.
        if self.content_profile is not None and event.turn_id is not None:
            payload_dict = event.payload.as_dict()
            cto_index = payload_dict.get("cto_index")
            if isinstance(cto_index, dict):
                profile = cto_index.get("content_profile")
                if isinstance(profile, dict):
                    if profile.get("id") != self.content_profile:
                        return False

        return True


# ---------------------------------------------------------------------------
# Concrete backends
# ---------------------------------------------------------------------------


@dataclass
class JsonlArchivistBackendConfig(ArchivistBackendConfig):
    """
    Configuration for JsonlArchivistBackend.

    Extends ArchivistBackendConfig with the output path. Each accepted event
    is serialized as one JSON line and appended to this file.

    Attributes:
        path: Destination file path. Parent directories are created on first
            write if absent. If the file already exists, records are appended.
    """

    path: Path = field(default_factory=lambda: Path("archivist.jsonl"))


class JsonlArchivistBackend:
    """
    Stream-shape Archivist backend that appends one JSON line per event.

    Each accepted event is serialized via hub_event_record() and written as
    a single JSON line (sort_keys=True for stable output) to the configured
    path. Parent directories are created on first write.

    is_durable = True — records are written to disk and survive process
    termination, subject to OS-level write guarantees.

    File I/O is synchronous (blocking) in v0. This is acceptable for the
    expected write volume; async file I/O is noted as a future improvement.

    No deduplication — records are appended unconditionally. The hub
    guarantees each event is delivered once; InMemoryPersistencePurpose
    is the canonical idempotent failover double if deduplication is needed.
    """

    is_durable: bool = True

    def __init__(self, config: JsonlArchivistBackendConfig) -> None:
        """
        Initialise the backend with its configuration.

        Args:
            config: JsonlArchivistBackendConfig carrying the output path and
                any event_type / content_profile filters.
        """
        self._config = config

    async def accept(self, event: HubEvent) -> None:
        """
        Serialize event and append one JSON line to the configured path.

        Creates parent directories if absent. Appends to an existing file
        so that a process restart picks up where the previous run left off.

        Args:
            event: The HubEvent to persist.
        """
        self._config.path.parent.mkdir(parents=True, exist_ok=True)
        record = hub_event_record(event)
        line = json.dumps(record, sort_keys=True)
        with self._config.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
