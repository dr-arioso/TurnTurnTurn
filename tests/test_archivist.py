"""Tests for the Archivist PersistencePurpose subclass."""

from __future__ import annotations

from uuid import uuid4

import pytest
from conftest import RecordingPurpose

from turnturnturn import TTT
from turnturnturn.archivist import (
    Archivist,
    ArchivistBackendConfig,
    JsonlArchivistBackend,
    JsonlArchivistBackendConfig,
)
from turnturnturn.events.hub_events import (
    CTOStartedPayload,
    EmptyPayload,
    HubEvent,
    HubEventType,
)

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class CapturingBackend:
    """Backend that records every accepted event for assertion."""

    is_durable: bool = False

    def __init__(self) -> None:
        self.received: list[HubEvent] = []

    async def accept(self, event: HubEvent) -> None:
        """Append event to the received list."""
        self.received.append(event)


class DurableCapturingBackend(CapturingBackend):
    """Durable variant of CapturingBackend."""

    is_durable: bool = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    event_type: HubEventType = HubEventType.PURPOSE_STARTED,
    turn_id=None,
    payload=None,
) -> HubEvent:
    """Construct a minimal HubEvent."""
    return HubEvent(
        event_type=event_type,
        event_id=uuid4(),
        created_at_ms=0,
        session_id=uuid4(),
        turn_id=turn_id,
        payload=payload or EmptyPayload(),
    )


def _make_cto_started_event(content_profile_id: str = "conversation") -> HubEvent:
    """Construct a CTO_STARTED event with a cto_index."""
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


# ---------------------------------------------------------------------------
# is_durable
# ---------------------------------------------------------------------------


def test_archivist_is_durable_true_when_any_backend_is_durable():
    """is_durable is True when at least one backend is durable."""
    non_durable = CapturingBackend()
    durable = DurableCapturingBackend()
    archivist = Archivist(
        backends=[
            (ArchivistBackendConfig(), non_durable),
            (ArchivistBackendConfig(), durable),
        ]
    )
    assert archivist.is_durable is True


def test_archivist_is_durable_false_when_no_durable_backend():
    """is_durable is False when no configured backend is durable."""
    archivist = Archivist(
        backends=[
            (ArchivistBackendConfig(), CapturingBackend()),
            (ArchivistBackendConfig(), CapturingBackend()),
        ]
    )
    assert archivist.is_durable is False


def test_archivist_is_durable_false_with_empty_backend_list():
    """is_durable is False when no backends are configured."""
    archivist = Archivist(backends=[])
    assert archivist.is_durable is False


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_archivist_routes_event_to_matching_backends():
    """accept() is called on backends whose config filter matches the event."""
    backend = CapturingBackend()
    config = ArchivistBackendConfig(event_types={HubEventType.PURPOSE_STARTED})
    archivist = Archivist(backends=[(config, backend)])

    event = _make_event(event_type=HubEventType.PURPOSE_STARTED)
    await archivist._handle_event(event)

    assert len(backend.received) == 1
    assert backend.received[0] is event


@pytest.mark.asyncio
async def test_archivist_does_not_route_to_filtered_out_backends():
    """accept() is not called on backends whose config filter rejects the event."""
    backend = CapturingBackend()
    config = ArchivistBackendConfig(event_types={HubEventType.DELTA_MERGED})
    archivist = Archivist(backends=[(config, backend)])

    event = _make_event(event_type=HubEventType.CTO_STARTED)
    await archivist._handle_event(event)

    assert len(backend.received) == 0


@pytest.mark.asyncio
async def test_archivist_multiple_backends_all_receive_matching_event():
    """All backends whose filter matches receive the event."""
    backend_a = CapturingBackend()
    backend_b = CapturingBackend()
    archivist = Archivist(
        backends=[
            (ArchivistBackendConfig(), backend_a),
            (ArchivistBackendConfig(), backend_b),
        ]
    )

    event = _make_event()
    await archivist._handle_event(event)

    assert len(backend_a.received) == 1
    assert len(backend_b.received) == 1


@pytest.mark.asyncio
async def test_archivist_different_profiles_route_to_different_backends():
    """Backends configured for different content profiles each receive only matching events."""
    convo_backend = CapturingBackend()
    annotation_backend = CapturingBackend()
    archivist = Archivist(
        backends=[
            (ArchivistBackendConfig(content_profile="conversation"), convo_backend),
            (ArchivistBackendConfig(content_profile="annotation"), annotation_backend),
        ]
    )

    convo_event = _make_cto_started_event(content_profile_id="conversation")
    annotation_event = _make_cto_started_event(content_profile_id="annotation")

    await archivist._handle_event(convo_event)
    await archivist._handle_event(annotation_event)

    assert len(convo_backend.received) == 1
    assert convo_backend.received[0] is convo_event
    assert len(annotation_backend.received) == 1
    assert annotation_backend.received[0] is annotation_event


# ---------------------------------------------------------------------------
# End-to-end via hub
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_archivist_end_to_end_via_hub(tmp_path):
    """Archivist registered as persistence Purpose writes JSONL records for real hub events."""
    import json

    jsonl_path = tmp_path / "events.jsonl"
    jsonl_config = JsonlArchivistBackendConfig(path=jsonl_path)
    jsonl_backend = JsonlArchivistBackend(jsonl_config)

    archivist = Archivist(backends=[(jsonl_config, jsonl_backend)])
    ttt = TTT.start(archivist)

    submitter = RecordingPurpose()
    submitter.name = "submitter"
    await ttt.start_purpose(submitter)

    await ttt.start_turn(
        "conversation",
        {"speaker": {"id": "usr_test"}, "text": "hello"},
        submitter.token,
    )

    lines = jsonl_path.read_text().splitlines()
    assert (
        len(lines) >= 2
    )  # at minimum: session_started + purpose_started + cto_started

    records = [json.loads(line) for line in lines]
    event_types = [r["event_type"] for r in records]

    assert event_types[0] == "session_started"
    assert "purpose_started" in event_types
    assert "cto_started" in event_types
