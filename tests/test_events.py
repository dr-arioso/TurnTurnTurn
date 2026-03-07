"""Tests for events.py — HubEvent, HubEventType, payload builder helpers.

Coverage areas:
  - HubEventType values
  - HubEvent construction and field access
  - HubEvent is frozen (immutable)
  - payload_cto_created() — required and optional fields, schema metadata
  - payload_delta_merged() — required fields, schema metadata
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from turnturnturn.events import (
    HubEvent,
    HubEventType,
    payload_cto_created,
    payload_delta_merged,
)

# ---------------------------------------------------------------------------
# HubEventType
# ---------------------------------------------------------------------------


def test_event_type_cto_created_value():
    assert HubEventType.CTO_CREATED.value == "cto_created"


def test_event_type_delta_merged_value():
    assert HubEventType.DELTA_MERGED.value == "delta_merged"


def test_event_type_is_str_enum():
    assert isinstance(HubEventType.CTO_CREATED, str)


# ---------------------------------------------------------------------------
# HubEvent
# ---------------------------------------------------------------------------


def test_hub_event_fields():
    eid = uuid4()
    sid = uuid4()
    event = HubEvent(
        event_type=HubEventType.CTO_CREATED,
        event_id=eid,
        created_at_ms=999,
        session_id=sid,
        hub_token="tok",
    )
    assert event.event_type == HubEventType.CTO_CREATED
    assert event.event_id == eid
    assert event.created_at_ms == 999
    assert event.session_id == sid
    assert event.hub_token == "tok"


def test_hub_event_is_frozen():
    event = HubEvent(
        event_type=HubEventType.CTO_CREATED,
        event_id=uuid4(),
        created_at_ms=0,
    )
    with pytest.raises((AttributeError, TypeError)):
        event.hub_token = "mutated"  # type: ignore[misc]


def test_hub_event_optional_fields_default_none():
    event = HubEvent(
        event_type=HubEventType.DELTA_MERGED,
        event_id=uuid4(),
        created_at_ms=0,
    )
    assert event.session_id is None
    assert event.turn_id is None
    assert event.payload is None
    assert event.hub_token is None


# ---------------------------------------------------------------------------
# payload_cto_created()
# ---------------------------------------------------------------------------


def _minimal_cto_index_dict() -> dict:
    return {
        "turn_id": str(uuid4()),
        "session_id": str(uuid4()),
        "content_profile": {"id": "conversation", "version": 1},
        "created_at_ms": 0,
    }


def test_payload_cto_created_schema_fields():
    p = payload_cto_created(cto_index_dict=_minimal_cto_index_dict())
    assert p["_schema"] == "cto_created"
    assert p["_v"] == 1


def test_payload_cto_created_contains_cto_index():
    idx = _minimal_cto_index_dict()
    p = payload_cto_created(cto_index_dict=idx)
    assert p["cto_index"] == idx


def test_payload_cto_created_optional_submitter_fields_default_none():
    p = payload_cto_created(cto_index_dict=_minimal_cto_index_dict())
    assert p["submitted_by_purpose_id"] is None
    assert p["submitted_by_purpose_name"] is None
    assert p["submitted_by_label"] is None


def test_payload_cto_created_submitter_label():
    p = payload_cto_created(
        cto_index_dict=_minimal_cto_index_dict(),
        submitted_by_label="test_caller",
    )
    assert p["submitted_by_label"] == "test_caller"


def test_payload_cto_created_submitter_purpose_fields():
    pid = str(uuid4())
    p = payload_cto_created(
        cto_index_dict=_minimal_cto_index_dict(),
        submitted_by_purpose_id=pid,
        submitted_by_purpose_name="my_purpose",
    )
    assert p["submitted_by_purpose_id"] == pid
    assert p["submitted_by_purpose_name"] == "my_purpose"


# ---------------------------------------------------------------------------
# payload_delta_merged()
# ---------------------------------------------------------------------------


def test_payload_delta_merged_schema_fields():
    p = payload_delta_merged(
        delta_dict={"delta_id": str(uuid4())},
        cto_index_dict=_minimal_cto_index_dict(),
    )
    assert p["_schema"] == "delta_merged"
    assert p["_v"] == 1


def test_payload_delta_merged_contains_delta_and_index():
    delta = {"delta_id": str(uuid4()), "patch": {"x": [1]}}
    idx = _minimal_cto_index_dict()
    p = payload_delta_merged(delta_dict=delta, cto_index_dict=idx)
    assert p["delta"] == delta
    assert p["cto_index"] == idx
