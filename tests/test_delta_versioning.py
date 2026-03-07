"""Tests for delta versioning (last_event_id / based_on_event_id / stale_delta).

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

Staleness detection in merge_delta
  - fresh Delta (based_on_event_id == cto.last_event_id) → stale_delta=False
  - stale Delta (based_on_event_id != cto.last_event_id) → stale_delta=True, merge still succeeds
  - Delta with based_on_event_id=None against a versioned CTO → stale_delta=True
  - stale_delta=False when cto.last_event_id is None (pre-versioning CTO)
  - stale_delta present in delta_merged event payload
  - stale_delta=False does not appear in payload for a fresh delta on a None-versioned CTO
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
    cto = hub.get_cto(turn_id)
    assert cto.last_event_id is not None
    assert isinstance(cto.last_event_id, UUID)


@pytest.mark.asyncio
async def test_start_turn_last_event_id_matches_emitted_event_id(
    hub, session_id, minimal_content
):
    """CTO.last_event_id must equal the event_id of the cto_created event."""
    p = RecordingPurpose()
    await hub.register_purpose(p)

    turn_id = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )

    emitted_event_id = p.received[0].event_id
    cto = hub.get_cto(turn_id)
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
    assert hub.get_cto(t1).last_event_id != hub.get_cto(t2).last_event_id


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
    cto = hub.get_cto(turn_id)
    idx = cto.to_index()
    assert idx.last_event_id == cto.last_event_id


@pytest.mark.asyncio
async def test_cto_index_in_event_payload_carries_last_event_id(
    hub, session_id, minimal_content
):
    """The cto_index dict in the cto_created payload must include last_event_id."""
    p = RecordingPurpose()
    await hub.register_purpose(p)

    turn_id = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )

    cto = hub.get_cto(turn_id)
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
    original_last_event_id = hub.get_cto(turn_id).last_event_id

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

    updated_cto = hub.get_cto(turn_id)
    assert updated_cto.last_event_id == event_id
    assert updated_cto.last_event_id != original_last_event_id


@pytest.mark.asyncio
async def test_merge_delta_last_event_id_matches_emitted_event_id(
    hub, session_id, minimal_content
):
    """CTO.last_event_id after merge must equal the emitted delta_merged event_id."""
    p = RecordingPurpose()
    await hub.register_purpose(p)

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
    assert hub.get_cto(turn_id).last_event_id == emitted_event_id


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
    assert hub.get_cto(turn_id).last_event_id == eid2


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
# Staleness detection — stale_delta flag in merge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fresh_delta_stale_flag_false(hub, session_id, minimal_content):
    """A Delta with the correct based_on_event_id must produce stale_delta=False."""
    p = RecordingPurpose()
    await hub.register_purpose(p)

    turn_id = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )
    current_last_event_id = hub.get_cto(turn_id).last_event_id
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

    payload = p.received[0].payload
    assert payload["stale_delta"] is False


@pytest.mark.asyncio
async def test_stale_delta_flag_true_on_mismatch(hub, session_id, minimal_content):
    """A Delta based on an old event_id must produce stale_delta=True."""
    p = RecordingPurpose()
    await hub.register_purpose(p)

    turn_id = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )
    # Capture the event_id the CTO was created at
    original_event_id = hub.get_cto(turn_id).last_event_id

    # Advance the CTO state with one merge
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
    p.received.clear()

    # Now propose a second Delta still based on the original (now stale) event_id
    await hub.merge_delta(
        Delta(
            delta_id=uuid4(),
            session_id=session_id,
            turn_id=turn_id,
            purpose_name="second",
            purpose_id=uuid4(),
            patch={"y": [2]},
            based_on_event_id=original_event_id,  # stale — CTO has since advanced
        )
    )

    payload = p.received[0].payload
    assert payload["stale_delta"] is True


@pytest.mark.asyncio
async def test_stale_merge_still_succeeds(hub, session_id, minimal_content):
    """A stale Delta must still be merged — the flag is informational, not a rejection."""
    turn_id = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )
    original_event_id = hub.get_cto(turn_id).last_event_id

    # Advance state
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

    # Stale merge — should not raise
    await hub.merge_delta(
        Delta(
            delta_id=uuid4(),
            session_id=session_id,
            turn_id=turn_id,
            purpose_name="second",
            purpose_id=uuid4(),
            patch={"y": [2]},
            based_on_event_id=original_event_id,
        )
    )

    obs = hub.get_cto(turn_id).observations
    assert "first" in obs
    assert "second" in obs


@pytest.mark.asyncio
async def test_none_based_on_event_id_against_versioned_cto_is_stale(
    hub, session_id, minimal_content
):
    """A None based_on_event_id is unverifiable when CTO.last_event_id is set → stale_delta=True."""
    p = RecordingPurpose()
    await hub.register_purpose(p)

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
            based_on_event_id=None,  # did not record version handle
        )
    )

    assert p.received[0].payload["stale_delta"] is True


@pytest.mark.asyncio
async def test_none_based_on_event_id_against_unversioned_cto_not_stale(
    hub, session_id
):
    """Against a CTO with last_event_id=None (pre-versioning), None based_on_event_id is not stale."""
    # Construct an unversioned CTO and inject it directly into the hub store.
    # This simulates a CTO that predates delta versioning.
    cto = CTO(
        turn_id=uuid4(),
        session_id=session_id,
        created_at_ms=0,
        content_profile={"id": "conversation", "version": 1},
        content={"speaker": {"id": "x", "role": "user", "label": "X"}, "text": "hi"},
        last_event_id=None,
    )
    hub._ctos[cto.turn_id] = cto

    p = RecordingPurpose()
    await hub.register_purpose(p)

    await hub.merge_delta(
        Delta(
            delta_id=uuid4(),
            session_id=session_id,
            turn_id=cto.turn_id,
            purpose_name="p",
            purpose_id=uuid4(),
            patch={"x": [1]},
            based_on_event_id=None,
        )
    )

    assert p.received[0].payload["stale_delta"] is False


@pytest.mark.asyncio
async def test_stale_delta_flag_present_in_payload(hub, session_id, minimal_content):
    """stale_delta key must always be present in delta_merged payload."""
    p = RecordingPurpose()
    await hub.register_purpose(p)

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

    assert "stale_delta" in p.received[0].payload


@pytest.mark.asyncio
async def test_stale_delta_uses_wrong_event_id(hub, session_id, minimal_content):
    """A completely fabricated based_on_event_id is detected as stale."""
    p = RecordingPurpose()
    await hub.register_purpose(p)

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
            based_on_event_id=uuid4(),  # fabricated — will not match
        )
    )

    assert p.received[0].payload["stale_delta"] is True
