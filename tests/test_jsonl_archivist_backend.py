"""Tests for JsonlArchivistBackend."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from turnturnturn.archivist import JsonlArchivistBackend, JsonlArchivistBackendConfig
from turnturnturn.events.hub_events import (
    CTOStartedPayload,
    EmptyPayload,
    HubEvent,
    HubEventType,
)


def _make_event(
    event_type: HubEventType = HubEventType.PURPOSE_STARTED,
    turn_id=None,
    payload=None,
) -> HubEvent:
    """Construct a minimal HubEvent for backend testing."""
    return HubEvent(
        event_type=event_type,
        event_id=uuid4(),
        created_at_ms=0,
        session_id=uuid4(),
        turn_id=turn_id,
        payload=payload or EmptyPayload(),
    )


def _make_cto_started_event(content_profile_id: str = "conversation") -> HubEvent:
    """Construct a CTO_STARTED event with a cto_index carrying content_profile."""
    turn_id = uuid4()
    return HubEvent(
        event_type=HubEventType.CTO_STARTED,
        event_id=uuid4(),
        created_at_ms=0,
        session_id=uuid4(),
        turn_id=turn_id,
        payload=CTOStartedPayload(
            cto_index={
                "turn_id": str(turn_id),
                "session_id": str(uuid4()),
                "content_profile": {"id": content_profile_id, "version": 1},
                "created_at_ms": 0,
                "last_event_id": str(uuid4()),
            },
        ),
    )


@pytest.mark.asyncio
async def test_jsonl_backend_writes_event_record(tmp_path):
    """accept() writes a single readable JSON record to the configured path."""
    path = tmp_path / "events.jsonl"
    config = JsonlArchivistBackendConfig(path=path)
    backend = JsonlArchivistBackend(config)

    event = _make_event()
    await backend.accept(event)

    lines = path.read_text().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["event_id"] == str(event.event_id)


@pytest.mark.asyncio
async def test_jsonl_backend_appends_across_multiple_events(tmp_path):
    """Each call to accept() appends a new line; existing records are preserved."""
    path = tmp_path / "events.jsonl"
    config = JsonlArchivistBackendConfig(path=path)
    backend = JsonlArchivistBackend(config)

    events = [_make_event() for _ in range(3)]
    for event in events:
        await backend.accept(event)

    lines = path.read_text().splitlines()
    assert len(lines) == 3
    ids = [json.loads(line)["event_id"] for line in lines]
    assert ids == [str(e.event_id) for e in events]


@pytest.mark.asyncio
async def test_jsonl_backend_creates_parent_dirs(tmp_path):
    """accept() creates missing parent directories before writing."""
    path = tmp_path / "a" / "b" / "c" / "events.jsonl"
    config = JsonlArchivistBackendConfig(path=path)
    backend = JsonlArchivistBackend(config)

    await backend.accept(_make_event())

    assert path.exists()


@pytest.mark.asyncio
async def test_jsonl_backend_restart_appends_to_existing_file(tmp_path):
    """A new backend instance targeting an existing file appends rather than truncates."""
    path = tmp_path / "events.jsonl"

    config = JsonlArchivistBackendConfig(path=path)
    backend_a = JsonlArchivistBackend(config)
    await backend_a.accept(_make_event())

    backend_b = JsonlArchivistBackend(config)
    await backend_b.accept(_make_event())

    lines = path.read_text().splitlines()
    assert len(lines) == 2


@pytest.mark.asyncio
async def test_jsonl_backend_respects_event_type_filter(tmp_path):
    """Events whose type is not in event_types are not written."""
    path = tmp_path / "events.jsonl"
    config = JsonlArchivistBackendConfig(
        path=path,
        event_types={HubEventType.DELTA_MERGED},
    )
    backend = JsonlArchivistBackend(config)

    # This event type is filtered out at the Archivist level; backend should
    # not be called. We test the config.matches() contract directly here
    # since JsonlArchivistBackend.accept() does not re-check filters.
    cto_event = _make_event(event_type=HubEventType.CTO_STARTED)
    delta_event = _make_event(event_type=HubEventType.DELTA_MERGED)

    assert not config.matches(cto_event)
    assert config.matches(delta_event)

    # Writing only the matching event produces exactly one record.
    await backend.accept(delta_event)
    lines = path.read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["event_type"] == "delta_merged"


@pytest.mark.asyncio
async def test_jsonl_backend_respects_content_profile_filter(tmp_path):
    """config.matches() returns False for CTO events with a non-matching profile."""
    path = tmp_path / "events.jsonl"
    config = JsonlArchivistBackendConfig(
        path=path,
        content_profile="conversation",
    )
    backend = JsonlArchivistBackend(config)

    matching_event = _make_cto_started_event(content_profile_id="conversation")
    non_matching_event = _make_cto_started_event(content_profile_id="annotation")
    non_cto_event = _make_event(event_type=HubEventType.PURPOSE_STARTED)

    assert config.matches(matching_event)
    assert not config.matches(non_matching_event)
    # Non-CTO events always pass the content_profile filter.
    assert config.matches(non_cto_event)

    # Writing only the matching and non-CTO events produces two records.
    await backend.accept(matching_event)
    await backend.accept(non_cto_event)
    lines = path.read_text().splitlines()
    assert len(lines) == 2


def test_jsonl_backend_event_record_keys(tmp_path):
    """Each written record contains exactly the expected top-level keys."""
    import asyncio

    path = tmp_path / "events.jsonl"
    config = JsonlArchivistBackendConfig(path=path)
    backend = JsonlArchivistBackend(config)

    asyncio.run(backend.accept(_make_event()))

    record = json.loads(path.read_text().splitlines()[0])
    assert set(record.keys()) == {
        "record_type",
        "event_type",
        "event_id",
        "created_at_ms",
        "session_id",
        "turn_id",
        "payload",
    }


def test_jsonl_backend_sort_keys_stable(tmp_path):
    """Records written with sort_keys=True produce identical output on re-parse."""
    import asyncio

    path = tmp_path / "events.jsonl"
    config = JsonlArchivistBackendConfig(path=path)
    backend = JsonlArchivistBackend(config)

    event = _make_event()
    asyncio.run(backend.accept(event))
    asyncio.run(backend.accept(event))

    lines = path.read_text().splitlines()
    # Both lines represent the same event and must be byte-for-byte identical.
    assert lines[0] == lines[1]
