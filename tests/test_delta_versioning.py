"""Tests for delta versioning (last_event_id / based_on_event_id).

Coverage areas:

CTO / CTOIndex — last_event_id field
  - start_turn sets CTO.last_event_id to the cto_created event_id
  - cto_created event_id matches CTO.last_event_id
  - CTOIndex.last_event_id mirrors CTO.last_event_id
  - cto_index in event payload carries last_event_id
  - merge_delta updates CTO.last_event_id to the delta_merged event_id
  - consecutive merges each advance last_event_id
  - last_event_id serialises correctly in to_dict (string or None)
  - CTOs constructed without last_event_id default to None

Delta — based_on_event_id field
  - based_on_event_id defaults to None
  - based_on_event_id is included in to_dict (string or None)
  - Delta with an explicit based_on_event_id serialises correctly

based_on_event_id as provenance (not conflict detection)
  - based_on_event_id is carried in the delta_merged payload (via serialised Delta)
  - merge succeeds regardless of based_on_event_id value — no rejection
  - stale_delta field is absent from delta_merged payload (retired in v0.18)
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from conftest import RecordingPurpose

from turnturnturn import CTO, CTOIndex, Delta

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_unversioned_cto() -> CTO:
    """A CTO built without going through start_turn — last_event_id is None."""
    return CTO(
        turn_id=uuid4(),
        session_id=uuid4(),
        created_at_ms=0,
        content_profile={"id": "conversation", "version": 1},
        content={"speaker": {"id": "x", "role": "user", "label": "X"}, "text": "hi"},
    )


# ---------------------------------------------------------------------------
# CTO.last_event_id — set at construction by start_turn
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_turn_sets_last_event_id(hub, session_id, minimal_content):
    turn_id = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )
    cto = hub.librarian.get_cto(turn_id)
    assert cto.last_event_id is not None
    assert isinstance(cto.last_event_id, UUID)


@pytest.mark.asyncio
async def test_start_turn_last_event_id_matches_emitted_event_id(
    hub, session_id, minimal_content
):
    """CTO.last_event_id must equal the event_id of the cto_created event."""
    p = RecordingPurpose()
    await hub.start_purpose(p)

    turn_id = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )

    emitted_event_id = p.received[0].event_id
    cto = hub.librarian.get_cto(turn_id)
    assert cto.last_event_id == emitted_event_id


@pytest.mark.asyncio
async def test_start_turn_last_event_ids_are_unique_across_turns(
    hub, session_id, minimal_content
):
    t1 = await hub.start_turn(
        session_id=session_id, content_profile="conversation", content=minimal_content
    )
    t2 = await hub.start_turn(
        session_id=session_id, content_profile="conversation", content=minimal_content
    )
    assert (
        hub.librarian.get_cto(t1).last_event_id
        != hub.librarian.get_cto(t2).last_event_id
    )


# ---------------------------------------------------------------------------
# CTOIndex.last_event_id — mirrors CTO
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cto_to_index_carries_last_event_id(hub, session_id, minimal_content):
    turn_id = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )
    cto = hub.librarian.get_cto(turn_id)
    idx = cto.to_index()
    assert idx.last_event_id == cto.last_event_id


@pytest.mark.asyncio
async def test_cto_index_in_event_payload_carries_last_event_id(
    hub, session_id, minimal_content
):
    """The cto_index dict in the cto_created payload must include last_event_id."""
    p = RecordingPurpose()
    await hub.start_purpose(p)

    turn_id = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )

    cto = hub.librarian.get_cto(turn_id)
    payload_index = p.received[0].payload["cto_index"]
    assert payload_index["last_event_id"] == str(cto.last_event_id)


def test_cto_index_last_event_id_none_serialises_as_none():
    idx = CTOIndex(
        turn_id=uuid4(),
        session_id=uuid4(),
        content_profile={"id": "conversation", "version": 1},
        created_at_ms=0,
        last_event_id=None,
    )
    assert idx.to_dict()["last_event_id"] is None


def test_cto_index_last_event_id_uuid_serialises_as_string():
    eid = uuid4()
    idx = CTOIndex(
        turn_id=uuid4(),
        session_id=uuid4(),
        content_profile={"id": "conversation", "version": 1},
        created_at_ms=0,
        last_event_id=eid,
    )
    d = idx.to_dict()
    assert isinstance(d["last_event_id"], str)
    assert UUID(d["last_event_id"]) == eid


# ---------------------------------------------------------------------------
# CTO.last_event_id — updated by merge_delta
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_delta_updates_last_event_id(hub, session_id, minimal_content):
    turn_id = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )
    original_last_event_id = hub.librarian.get_cto(turn_id).last_event_id

    event_id = await hub.merge_delta(
        Delta(
            delta_id=uuid4(),
            session_id=session_id,
            turn_id=turn_id,
            purpose_name="p",
            purpose_id=uuid4(),
            patch={"x": [1]},
        )
    )

    updated_cto = hub.librarian.get_cto(turn_id)
    assert updated_cto.last_event_id == event_id
    assert updated_cto.last_event_id != original_last_event_id


@pytest.mark.asyncio
async def test_merge_delta_last_event_id_matches_emitted_event_id(
    hub, session_id, minimal_content
):
    """CTO.last_event_id after merge must equal the emitted delta_merged event_id."""
    p = RecordingPurpose()
    await hub.start_purpose(p)

    turn_id = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )
    p.received.clear()

    returned_event_id = await hub.merge_delta(
        Delta(
            delta_id=uuid4(),
            session_id=session_id,
            turn_id=turn_id,
            purpose_name="p",
            purpose_id=uuid4(),
            patch={"x": [1]},
        )
    )

    emitted_event_id = p.received[0].event_id
    assert returned_event_id == emitted_event_id
    assert hub.librarian.get_cto(turn_id).last_event_id == emitted_event_id


@pytest.mark.asyncio
async def test_consecutive_merges_each_advance_last_event_id(
    hub, session_id, minimal_content
):
    turn_id = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )
    pid = uuid4()

    eid1 = await hub.merge_delta(
        Delta(
            delta_id=uuid4(),
            session_id=session_id,
            turn_id=turn_id,
            purpose_name="p",
            purpose_id=pid,
            patch={"x": [1]},
        )
    )
    eid2 = await hub.merge_delta(
        Delta(
            delta_id=uuid4(),
            session_id=session_id,
            turn_id=turn_id,
            purpose_name="p",
            purpose_id=pid,
            patch={"x": [2]},
        )
    )

    assert eid1 != eid2
    assert hub.librarian.get_cto(turn_id).last_event_id == eid2


# ---------------------------------------------------------------------------
# CTO.last_event_id — serialisation
# ---------------------------------------------------------------------------


def test_cto_last_event_id_none_serialises_as_none():
    cto = _make_unversioned_cto()
    assert cto.to_dict()["last_event_id"] is None


def test_cto_last_event_id_uuid_serialises_as_string():
    eid = uuid4()
    cto = CTO(
        turn_id=uuid4(),
        session_id=uuid4(),
        created_at_ms=0,
        content_profile={"id": "conversation", "version": 1},
        content={"speaker": {"id": "x", "role": "user", "label": "X"}, "text": "hi"},
        last_event_id=eid,
    )
    d = cto.to_dict()
    assert isinstance(d["last_event_id"], str)
    assert UUID(d["last_event_id"]) == eid


def test_cto_default_last_event_id_is_none():
    cto = _make_unversioned_cto()
    assert cto.last_event_id is None


# ---------------------------------------------------------------------------
# Delta.based_on_event_id
# ---------------------------------------------------------------------------


def test_delta_based_on_event_id_defaults_to_none():
    d = Delta(
        delta_id=uuid4(),
        session_id=uuid4(),
        turn_id=uuid4(),
        purpose_name="p",
        purpose_id=uuid4(),
        patch={"x": [1]},
    )
    assert d.based_on_event_id is None


def test_delta_based_on_event_id_none_serialises_as_none():
    d = Delta(
        delta_id=uuid4(),
        session_id=uuid4(),
        turn_id=uuid4(),
        purpose_name="p",
        purpose_id=uuid4(),
        patch={"x": [1]},
    )
    assert d.to_dict()["based_on_event_id"] is None


def test_delta_based_on_event_id_uuid_serialises_as_string():
    eid = uuid4()
    d = Delta(
        delta_id=uuid4(),
        session_id=uuid4(),
        turn_id=uuid4(),
        purpose_name="p",
        purpose_id=uuid4(),
        patch={"x": [1]},
        based_on_event_id=eid,
    )
    result = d.to_dict()
    assert isinstance(result["based_on_event_id"], str)
    assert UUID(result["based_on_event_id"]) == eid


# ---------------------------------------------------------------------------
# based_on_event_id as provenance — not conflict detection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_based_on_event_id_carried_in_delta_merged_payload(
    hub, session_id, minimal_content
):
    """based_on_event_id must appear in the serialised Delta in the payload."""
    p = RecordingPurpose()
    await hub.start_purpose(p)

    turn_id = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )
    current_last_event_id = hub.librarian.get_cto(turn_id).last_event_id
    p.received.clear()

    await hub.merge_delta(
        Delta(
            delta_id=uuid4(),
            session_id=session_id,
            turn_id=turn_id,
            purpose_name="p",
            purpose_id=uuid4(),
            patch={"x": [1]},
            based_on_event_id=current_last_event_id,
        )
    )

    delta_in_payload = p.received[0].payload["delta"]
    assert delta_in_payload["based_on_event_id"] == str(current_last_event_id)


@pytest.mark.asyncio
async def test_merge_succeeds_regardless_of_based_on_event_id(
    hub, session_id, minimal_content
):
    """based_on_event_id is provenance only — any value (including stale) is merged."""
    turn_id = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )
    original_event_id = hub.librarian.get_cto(turn_id).last_event_id

    # Advance CTO state past the original event_id
    await hub.merge_delta(
        Delta(
            delta_id=uuid4(),
            session_id=session_id,
            turn_id=turn_id,
            purpose_name="first",
            purpose_id=uuid4(),
            patch={"x": [1]},
            based_on_event_id=original_event_id,
        )
    )

    # Propose a second Delta still referencing the now-superseded event_id.
    # The hub must merge it without raising — no conflict rejection.
    await hub.merge_delta(
        Delta(
            delta_id=uuid4(),
            session_id=session_id,
            turn_id=turn_id,
            purpose_name="second",
            purpose_id=uuid4(),
            patch={"y": [2]},
            based_on_event_id=original_event_id,  # superseded, but provenance only
        )
    )

    obs = hub.librarian.get_cto(turn_id).observations
    assert "first" in obs
    assert "second" in obs


@pytest.mark.asyncio
async def test_delta_merged_payload_has_no_stale_delta_field(
    hub, session_id, minimal_content
):
    """stale_delta was retired in v0.18 — must not appear in delta_merged payload."""
    p = RecordingPurpose()
    await hub.start_purpose(p)

    turn_id = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )
    p.received.clear()

    await hub.merge_delta(
        Delta(
            delta_id=uuid4(),
            session_id=session_id,
            turn_id=turn_id,
            purpose_name="p",
            purpose_id=uuid4(),
            patch={"x": [1]},
        )
    )

    assert "stale_delta" not in p.received[0].payload
