"""
Archivist — pluggable durable persistence for TTT event streams.

This module defines the backend protocol, configuration, concrete backends,
and the Archivist PersistencePurpose subclass that wires them to the hub.

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

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable
from uuid import uuid4

from ._event_serialization import (
    _event_type_value,
    hub_event_record,
    purpose_event_record,
)
from .cto_json import load_cto_json_document, normalize_cto_json_document
from .events import PurposeEventType
from .events.hub_events import HubEvent, HubEventType
from .events.purpose_events import (
    CTOImported,
    CTOImportedPayload,
    RequestCTOPayload,
)
from .persistence import PersistencePurpose
from .protocols import EventProtocol, PurposeEventProtocol

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

    async def accept(self, event: EventProtocol) -> None:
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

    def matches(self, event: EventProtocol) -> bool:
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
        if self.event_types is not None:
            allowed = {_event_type_value(event_type) for event_type in self.event_types}
            if _event_type_value(event.event_type) not in allowed:
                return False

        # Content profile filter only applies to CTO-scoped events.
        # Non-CTO events (session lifecycle, purpose lifecycle) are not
        # associated with a profile and always pass this filter.
        if (
            self.content_profile is not None
            and isinstance(event, HubEvent)
            and event.turn_id is not None
        ):
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

    async def accept(self, event: EventProtocol) -> None:
        """
        Serialize event and append one JSON line to the configured path.

        Creates parent directories if absent. Appends to an existing file
        so that a process restart picks up where the previous run left off.

        Args:
            event: The HubEvent to persist.
        """
        self._config.path.parent.mkdir(parents=True, exist_ok=True)
        record = (
            hub_event_record(event)
            if isinstance(event, HubEvent)
            else purpose_event_record(_as_purpose_event(event))
        )
        line = json.dumps(record, sort_keys=True)
        with self._config.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


# ---------------------------------------------------------------------------
# Document-shape backend
# ---------------------------------------------------------------------------


@dataclass
class SessionDocumentArchivistBackendConfig(ArchivistBackendConfig):
    """
    Configuration for SessionDocumentArchivistBackend.

    Extends ArchivistBackendConfig with the output path. The backend
    accumulates all accepted events in memory and flushes them as a single
    JSON document when SESSION_COMPLETED is received.

    Attributes:
        path: Destination file path for the session document. Parent
            directories are created on flush if absent. If the file already
            exists it is overwritten — the document represents one complete
            session record.
    """

    path: Path = field(default_factory=lambda: Path("session.json"))


class SessionDocumentArchivistBackend:
    """
    Document-shape Archivist backend that flushes one JSON file per session.

    Accumulates accepted events in memory as accept() is called. On
    SESSION_COMPLETED, writes a single JSON document to the configured path
    containing a metadata header and an ordered array of all accumulated
    events.

    Document shape:
        {
            "id":       <session_id of SESSION_COMPLETED or null>,
            "metadata": {},       # stub — TraceProbe-compatible header is
                                  # future work (v0.21+)
            "events":   [...]     # ordered list of hub_event_record() dicts
        }

    is_durable = True — the document is written to disk and survives process
    termination, subject to OS-level write guarantees. However, events
    accumulated in memory before a crash are lost; the JSONL backend is the
    safer choice when crash-durability of individual events is required.

    This backend is a stub in v0.20. The metadata header shape and full
    TraceProbe compatibility are deferred to a future release; the
    accumulate-and-flush pattern is what this version establishes.
    """

    is_durable: bool = True

    def __init__(self, config: SessionDocumentArchivistBackendConfig) -> None:
        """
        Initialise the backend with its configuration.

        Args:
            config: SessionDocumentArchivistBackendConfig carrying the output
                path and any event_type / content_profile filters.
        """
        self._config = config
        self._events: list[dict[str, Any]] = []

    async def accept(self, event: EventProtocol) -> None:
        """
        Accumulate the event; flush to disk on SESSION_COMPLETED.

        For all events other than SESSION_COMPLETED, the serialized record is
        appended to the in-memory list. When SESSION_COMPLETED arrives, the
        full accumulated list is written to the configured path as a single
        JSON document.

        SESSION_COMPLETED itself is included in the events array before
        flushing so the document contains a complete record of the session,
        including its closing event.

        Args:
            event: The HubEvent to accumulate or trigger a flush.
        """
        record = (
            hub_event_record(event)
            if isinstance(event, HubEvent)
            else purpose_event_record(_as_purpose_event(event))
        )
        self._events.append(record)

        if _event_type_value(event.event_type) == "session_completed":
            session_id = event.session_id if isinstance(event, HubEvent) else None
            self._flush(session_id=str(session_id) if session_id else None)

    def _flush(self, session_id: str | None) -> None:
        """
        Write the accumulated event list to disk as a single JSON document.

        Creates parent directories if absent. Overwrites any existing file at
        the configured path — this document represents one complete session.

        Args:
            session_id: The session identifier to embed in the document header.
                Sourced from the SESSION_COMPLETED event's session_id field.
        """
        document: dict[str, Any] = {
            "id": session_id,
            "metadata": {},  # stub — TraceProbe-compatible shape is future work
            "events": self._events,
        }
        self._config.path.parent.mkdir(parents=True, exist_ok=True)
        with self._config.path.open("w", encoding="utf-8") as f:
            json.dump(document, f, sort_keys=True)


# ---------------------------------------------------------------------------
# Archivist — PersistencePurpose subclass
# ---------------------------------------------------------------------------


class Archivist(PersistencePurpose):
    """
    Durable PersistencePurpose that fans events out to pluggable backends.

    From the hub's perspective, Archivist is an opaque persistence sink —
    it satisfies CTOPersistencePurposeProtocol and receives every event
    before any domain Purpose does. Internally it routes each event to the
    configured backends whose ArchivistBackendConfig filters match.

    is_durable is True if at least one configured backend declares
    is_durable = True. If no durable backend is configured, TTT.start()
    will emit a UserWarning, as with any non-durable persister.

    Usage::

        archivist = Archivist(
            backends=[
                (JsonlArchivistBackendConfig(path=Path("events.jsonl")),
                 JsonlArchivistBackend(...)),
                (SessionDocumentArchivistBackendConfig(path=Path("session.json")),
                 SessionDocumentArchivistBackend(...)),
            ]
        )
        ttt = TTT.start(archivist)
    """

    name = "archivist"

    def __init__(
        self,
        backends: list[tuple[ArchivistBackendConfig, ArchivistBackendProtocol]],
    ) -> None:
        """
        Initialise Archivist with a list of (config, backend) pairs.

        Each pair couples a filter configuration with the backend that should
        receive matching events. Backends are called in list order for each
        event; all matching backends receive the event regardless of whether
        earlier ones succeed.

        Args:
            backends: Ordered list of (ArchivistBackendConfig, backend) pairs.
                ArchivistBackendConfig.matches() is evaluated per event before
                calling backend.accept(). An empty list is valid — Archivist
                will accept all events from the hub and discard them silently.
        """
        super().__init__()
        self.id = uuid4()
        self._backends = backends
        self._handled_request_keys: set[str] = set()

    @property
    def is_durable(self) -> bool:
        """
        True if at least one configured backend is durable.

        Durability is declared by each backend via its is_durable class or
        instance attribute. Archivist is considered durable if any backend
        survives process termination — partial durability is better than none,
        and the JSONL backend is typically the durable anchor in a mixed
        configuration.
        """
        return any(
            getattr(backend, "is_durable", False) for _, backend in self._backends
        )

    async def _handle_event(self, event: HubEvent) -> None:
        """
        Fan the event out to all backends whose config filter matches.

        Iterates backends in order. For each pair, evaluates
        ArchivistBackendConfig.matches(event); if True, calls
        backend.accept(event) and awaits completion. Backends that do not
        match are skipped. All matching backends are called — a backend
        earlier in the list does not gate later ones.

        Args:
            event: The validated HubEvent received from the hub.
        """
        if _event_type_value(event.event_type) == PurposeEventType.REQUEST_CTO.value:
            await self._handle_request_cto(event)
            return

        await self._route_to_backends(event)
        if (
            event.event_type == HubEventType.SESSION_CLOSE_PENDING
            and event.session_id is not None
        ):
            payload_dict = event.payload.as_dict()
            session_code = (
                payload_dict.get("session_code")
                if isinstance(payload_dict, dict)
                else None
            )
            await self.complete_session_closing(str(event.session_id))
            await self.emit_session_completed(
                session_id=str(event.session_id),
                session_code=session_code if isinstance(session_code, str) else None,
            )

    async def _route_to_backends(self, event: EventProtocol) -> None:
        """Fan a validated event out to every matching Archivist backend."""
        for config, backend in self._backends:
            if config.matches(event):
                await backend.accept(event)

    async def _handle_request_cto(self, event: HubEvent) -> None:
        """Load a cto_json document, dedupe it, and emit cto_imported once."""
        payload = event.payload
        if not isinstance(payload, RequestCTOPayload):
            raise TypeError(
                "Archivist received request_cto without RequestCTOPayload payload"
            )
        if payload.source_kind != "cto_json":
            raise NotImplementedError(
                f"Archivist only supports source_kind='cto_json' in v1; got {payload.source_kind!r}"
            )

        source_path = Path(payload.source_locator).expanduser()
        document_bytes = source_path.read_bytes()
        content_hash = hashlib.sha256(document_bytes).hexdigest()
        request_key = (
            payload.request_id
            if payload.request_id is not None
            else f"{payload.source_kind}:{source_path.resolve()}:{content_hash}"
        )
        if request_key in self._handled_request_keys:
            return

        document = load_cto_json_document(source_path)
        normalized = normalize_cto_json_document(document)
        self._handled_request_keys.add(request_key)
        await self._submit_purpose_event(
            CTOImported(
                purpose_id=self.id,
                purpose_name=self.name,
                hub_token=self._require_token(),
                session_id=(
                    event.session_id if event.session_id is not None else uuid4()
                ),
                payload=CTOImportedPayload(
                    session_id=payload.session_id,
                    source_kind=payload.source_kind,
                    source_locator=str(source_path.resolve()),
                    source_content_hash=content_hash,
                    requested_by_purpose_id=payload.requested_by_purpose_id,
                    requested_by_purpose_name=payload.requested_by_purpose_name,
                    cto_json=normalized.document,
                    session_code=payload.session_code,
                    request_id=request_key,
                ),
            )
        )

    async def write_event(self, event: EventProtocol) -> None:
        """
        Persist an accepted event via the appropriate Archivist path.

        Accepted purpose events are written to backends as provenance records.
        Hub-authored downlink events continue through `_handle_event()`, which
        may trigger Archivist's additional behaviors such as `request_cto`
        import handling and final session completion authorship.

        Args:
            event: The accepted mesh event to persist.
        """
        if isinstance(event, HubEvent):
            await self._handle_event(event)
            return
        await self._route_to_backends(event)


def _as_purpose_event(event: EventProtocol) -> PurposeEventProtocol:
    """Narrow a non-hub event to the accepted purpose-event protocol."""
    assert isinstance(event, PurposeEventProtocol)
    return event
