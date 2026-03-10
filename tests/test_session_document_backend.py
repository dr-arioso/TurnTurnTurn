"""Tests for SessionDocumentArchivistBackend."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from turnturnturn.archivist import (
    SessionDocumentArchivistBackend,
    SessionDocumentArchivistBackendConfig,
)
from turnturnturn.events.hub_events import (
    EmptyPayload,
    HubEvent,
    HubEventType,
    SessionCompletedPayload,
)


def _make_event(
    event_type: HubEventType = HubEventType.CTO_STARTED,
    session_id=None,
    payload=None,
) -> HubEvent:
    """Construct a minimal HubEvent for backend testing."""
    return HubEvent(
        event_type=event_type,
        event_id=uuid4(),
        created_at_ms=0,
        session_id=session_id or uuid4(),
        turn_id=None,
        payload=payload or EmptyPayload(),
    )


def _make_session_completed_event(session_id=None) -> HubEvent:
    """Construct a SESSION_COMPLETED event."""
    return HubEvent(
        event_type=HubEventType.SESSION_COMPLETED,
        event_id=uuid4(),
        created_at_ms=0,
        session_id=session_id or uuid4(),
        turn_id=None,
        payload=SessionCompletedPayload(is_last_out=True),
    )


@pytest.mark.asyncio
async def test_session_document_backend_writes_on_session_completed(tmp_path):
    """The output file is created only when SESSION_COMPLETED is accepted."""
    path = tmp_path / "session.json"
    config = SessionDocumentArchivistBackendConfig(path=path)
    backend = SessionDocumentArchivistBackend(config)

    assert not path.exists()

    await backend.accept(_make_event())
    assert not path.exists()

    await backend.accept(_make_session_completed_event())
    assert path.exists()


@pytest.mark.asyncio
async def test_session_document_backend_accumulates_events_in_order(tmp_path):
    """All accepted events appear in the document in the order they were received."""
    path = tmp_path / "session.json"
    config = SessionDocumentArchivistBackendConfig(path=path)
    backend = SessionDocumentArchivistBackend(config)

    events = [_make_event() for _ in range(3)]
    for event in events:
        await backend.accept(event)

    completed = _make_session_completed_event()
    await backend.accept(completed)

    document = json.loads(path.read_text())
    # All three regular events plus SESSION_COMPLETED appear in the document.
    assert len(document["events"]) == 4
    expected_ids = [str(e.event_id) for e in events] + [str(completed.event_id)]
    actual_ids = [e["event_id"] for e in document["events"]]
    assert actual_ids == expected_ids


@pytest.mark.asyncio
async def test_session_document_backend_does_not_write_before_session_completed(
    tmp_path,
):
    """Accepting many events does not trigger a write until SESSION_COMPLETED."""
    path = tmp_path / "session.json"
    config = SessionDocumentArchivistBackendConfig(path=path)
    backend = SessionDocumentArchivistBackend(config)

    for _ in range(10):
        await backend.accept(_make_event())

    assert not path.exists()


@pytest.mark.asyncio
async def test_session_document_backend_output_is_valid_json(tmp_path):
    """The flushed file is valid JSON with the expected top-level structure."""
    session_id = uuid4()
    path = tmp_path / "session.json"
    config = SessionDocumentArchivistBackendConfig(path=path)
    backend = SessionDocumentArchivistBackend(config)

    await backend.accept(_make_event(session_id=session_id))
    await backend.accept(_make_session_completed_event(session_id=session_id))

    raw = path.read_text()
    document = json.loads(raw)  # raises if invalid JSON

    assert set(document.keys()) == {"id", "metadata", "events"}
    assert isinstance(document["events"], list)
    assert isinstance(document["metadata"], dict)
    # id is the session_id string from SESSION_COMPLETED
    assert document["id"] == str(session_id)
