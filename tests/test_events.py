"""Tests for the typed event and payload model."""

from __future__ import annotations

from uuid import uuid4

import pytest

from turnturnturn.delta import Delta
from turnturnturn.events import (
    CTOStartedPayload,
    DeltaMergedPayload,
    EmptyPayload,
    HubEvent,
    HubEventType,
    ProposeDelta,
    ProposeDeltaPayload,
    PurposeEventType,
)


def _minimal_cto_index_dict() -> dict:
    return {
        "turn_id": str(uuid4()),
        "session_id": str(uuid4()),
        "content_profile": {"id": "conversation", "version": 1},
        "created_at_ms": 0,
    }


def test_event_type_cto_started_value():
    assert HubEventType.CTO_STARTED.value == "cto_started"


def test_event_type_delta_merged_value():
    assert HubEventType.DELTA_MERGED.value == "delta_merged"


def test_event_type_propose_delta_value():
    assert PurposeEventType.PROPOSE_DELTA.value == "propose_delta"


def test_hub_event_fields():
    eid = uuid4()
    sid = uuid4()
    payload = EmptyPayload()
    event = HubEvent(
        event_type=HubEventType.CTO_STARTED,
        event_id=eid,
        created_at_ms=999,
        session_id=sid,
        payload=payload,
        hub_token="tok",
        downlink_signature="sig",
    )
    assert event.event_type == HubEventType.CTO_STARTED
    assert event.event_id == eid
    assert event.created_at_ms == 999
    assert event.session_id == sid
    assert event.payload is payload
    assert event.hub_token == "tok"
    assert event.downlink_signature == "sig"


def test_hub_event_is_frozen():
    event = HubEvent(
        event_type=HubEventType.CTO_STARTED,
        event_id=uuid4(),
        created_at_ms=0,
    )
    with pytest.raises((AttributeError, TypeError)):
        event.hub_token = "mutated"  # type: ignore[misc]


def test_empty_payload_serializes_to_empty_dict():
    assert EmptyPayload().as_dict() == {}


def test_cto_started_payload_as_dict():
    payload = CTOStartedPayload(
        cto_index={
            "turn_id": str(uuid4()),
            "session_id": str(uuid4()),
            "content_profile": {"id": "conversation", "version": 1},
            "created_at_ms": 0,
        }
    )
    data = payload.as_dict()
    assert data["_schema"] == "cto_started"
    assert data["_v"] == 1
    assert "cto_index" in data


def test_delta_merged_payload_as_dict():
    payload = DeltaMergedPayload(
        delta={"delta_id": str(uuid4()), "patch": {"x": [1]}},
        cto_index={
            "turn_id": str(uuid4()),
            "session_id": str(uuid4()),
            "content_profile": {"id": "conversation", "version": 1},
            "created_at_ms": 0,
        },
    )
    data = payload.as_dict()
    assert data["_schema"] == "delta_merged"
    assert data["_v"] == 1
    assert "delta" in data
    assert "cto_index" in data


def test_propose_delta_fields():
    pid = uuid4()
    delta = Delta(
        delta_id=uuid4(),
        session_id=uuid4(),
        turn_id=uuid4(),
        purpose_name="tester",
        purpose_id=pid,
        patch={"x": ["y"]},
    )
    payload = ProposeDeltaPayload(delta=delta)
    event = ProposeDelta(
        event_type=PurposeEventType.PROPOSE_DELTA,
        event_id=uuid4(),
        created_at_ms=123,
        purpose_id=pid,
        purpose_name="tester",
        hub_token="tok",
        payload=payload,
    )
    assert event.event_type == PurposeEventType.PROPOSE_DELTA
    assert event.purpose_id == pid
    assert event.purpose_name == "tester"
    assert event.hub_token == "tok"
    assert event.payload is payload


def test_propose_delta_payload_as_dict():
    delta = Delta(
        delta_id=uuid4(),
        session_id=uuid4(),
        turn_id=uuid4(),
        purpose_name="tester",
        purpose_id=uuid4(),
        patch={"x": ["y"]},
    )
    payload = ProposeDeltaPayload(delta=delta)
    assert payload.as_dict()["delta"]["purpose_name"] == "tester"
