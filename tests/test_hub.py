"""Tests for the TTT hub runtime (hub.py).

Coverage areas:
  - TTT.start() — profile loading, strict flag
  - start_purpose() — token/downlink assignment, re-registration
  - start_turn() — CTO creation, profile validation, event emission, dispatch
  - _merge_delta() via hub.take_turn() — append-only merge and event emission
  - ttt.librarian.get_cto() — read path, returns None for unknown turn_id
  - _multicast() — per-recipient route credential stamping
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from conftest import NamedPurpose, RecordingPurpose

from turnturnturn import CTO, TTT, Delta
from turnturnturn.errors import UnauthorizedDispatchError
from turnturnturn.events import (
    DeltaProposalEvent,
    DeltaProposalPayload,
    HubEventType,
    PurposeEventType,
)


def _proposal_event_for(delta: Delta, purpose) -> DeltaProposalEvent:
    return DeltaProposalEvent(
        event_type=PurposeEventType.DELTA_PROPOSAL,
        event_id=uuid4(),
        created_at_ms=0,
        purpose_id=purpose.id,
        purpose_name=purpose.name,
        hub_token=purpose.token,
        payload=DeltaProposalPayload(delta=delta),
    )


# ---------------------------------------------------------------------------
# TTT.start()
# ---------------------------------------------------------------------------


def test_start_returns_ttt_instance(persistence_purpose):
    hub = TTT.start(persistence_purpose)
    assert isinstance(hub, TTT)


def test_start_loads_conversation_profile(persistence_purpose):
    """TTT.start() must register the conversation profile so start_turn works."""
    hub = TTT.start(persistence_purpose)
    assert hub is not None


def test_start_strict_profiles_flag(persistence_purpose):
    hub = TTT.start(persistence_purpose, strict_profiles=True)
    assert hub.strict_profiles is True


def test_start_strict_profiles_default_false(persistence_purpose):
    hub = TTT.start(persistence_purpose)
    assert hub.strict_profiles is False


def test_start_exposes_librarian(persistence_purpose):
    """TTT.start() must wire ttt.librarian for CTO read access."""
    from turnturnturn.hub import Librarian

    hub = TTT.start(persistence_purpose)
    assert hasattr(hub, "librarian")
    assert isinstance(hub.librarian, Librarian)


# ---------------------------------------------------------------------------
# start_purpose()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_purpose_assigns_token(hub):
    p = RecordingPurpose()
    assert p.token is None  # unbound before registration
    await hub.start_purpose(p)
    assert p.token is not None
    assert isinstance(p.token, str)
    assert len(p.token) > 0
    assert p.downlink_signature is not None
    assert isinstance(p.downlink_signature, str)
    assert len(p.downlink_signature) > 0


@pytest.mark.asyncio
async def test_start_purpose_stores_registration(hub):
    p = RecordingPurpose()
    await hub.start_purpose(p)
    assert p.id in hub.registrations


@pytest.mark.asyncio
async def test_start_multiple_purposes_each_gets_unique_token(hub):
    p1 = RecordingPurpose()
    p2 = RecordingPurpose()
    await hub.start_purpose(p1)
    await hub.start_purpose(p2)
    assert p1.token != p2.token
    assert p1.downlink_signature != p2.downlink_signature


@pytest.mark.asyncio
async def test_restart_purpose_issues_new_token(hub):
    p = RecordingPurpose()
    await hub.start_purpose(p)
    first_token = p.token
    first_signature = p.downlink_signature

    await hub.start_purpose(p)

    assert p.token != first_token
    assert p.downlink_signature != first_signature


@pytest.mark.asyncio
async def test_start_raw_protocol_purpose_no_token(hub):
    """A bare PurposeProtocol implementor (test double) gets registered without a token."""

    class RawPurpose:
        name = "raw"
        id = uuid4()
        token = None
        received = []

        async def take_turn(self, event):
            self.received.append(event)

    raw = RawPurpose()
    await hub.start_purpose(raw)
    assert raw.id in hub.registrations
    assert hub.registrations[raw.id].token is None


# ---------------------------------------------------------------------------
# start_turn()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_turn_returns_uuid(hub, session_id, minimal_content, submitter):
    turn_id = await hub.start_turn(
        "conversation",
        minimal_content,
        submitter.token,
        session_id=session_id,
    )
    assert isinstance(turn_id, UUID)


@pytest.mark.asyncio
async def test_start_turn_stores_cto(hub, session_id, minimal_content, submitter):
    turn_id = await hub.start_turn(
        "conversation",
        minimal_content,
        submitter.token,
        session_id=session_id,
    )
    cto = hub.librarian.get_cto(turn_id)
    assert cto is not None
    assert isinstance(cto, CTO)
    assert cto.turn_id == turn_id
    assert cto.session_id == session_id


@pytest.mark.asyncio
async def test_start_turn_cto_content_profile_dict(
    hub, session_id, minimal_content, submitter
):
    """content_profile on the created CTO must be {"id": ..., "version": ...}."""
    turn_id = await hub.start_turn(
        "conversation",
        minimal_content,
        submitter.token,
        session_id=session_id,
    )
    cto = hub.librarian.get_cto(turn_id)
    assert cto.content_profile == {"id": "conversation", "version": 1}


@pytest.mark.asyncio
async def test_start_turn_applies_speaker_role_default(hub, session_id, submitter):
    turn_id = await hub.start_turn(
        "conversation",
        {"speaker": {"id": "usr_x"}, "text": "hi"},
        submitter.token,
        session_id=session_id,
    )
    cto = hub.librarian.get_cto(turn_id)
    assert cto.speaker_role == "speaker"


@pytest.mark.asyncio
async def test_start_turn_applies_speaker_label_default(hub, session_id, submitter):
    turn_id = await hub.start_turn(
        "conversation",
        {"speaker": {"id": "usr_x"}, "text": "hi"},
        submitter.token,
        session_id=session_id,
    )
    cto = hub.librarian.get_cto(turn_id)
    assert cto.speaker_label == "speaker_1"


@pytest.mark.asyncio
async def test_start_turn_speaker_label_ordinal_increments(hub, session_id, submitter):
    """Each distinct speaker.id within a session gets a new ordinal."""
    await hub.start_turn(
        "conversation",
        {"speaker": {"id": "a"}, "text": "first"},
        submitter.token,
        session_id=session_id,
    )
    t2 = await hub.start_turn(
        "conversation",
        {"speaker": {"id": "b"}, "text": "second"},
        submitter.token,
        session_id=session_id,
    )
    cto2 = hub.librarian.get_cto(t2)
    assert cto2.speaker_label == "speaker_2"


@pytest.mark.asyncio
async def test_start_turn_same_speaker_same_ordinal(hub, session_id, submitter):
    """The same speaker.id always resolves to the same label within a session."""
    t1 = await hub.start_turn(
        "conversation",
        {"speaker": {"id": "alice"}, "text": "turn 1"},
        submitter.token,
        session_id=session_id,
    )
    await hub.start_turn(
        "conversation",
        {"speaker": {"id": "bob"}, "text": "turn 2"},
        submitter.token,
        session_id=session_id,
    )
    t3 = await hub.start_turn(
        "conversation",
        {"speaker": {"id": "alice"}, "text": "turn 3"},
        submitter.token,
        session_id=session_id,
    )
    assert (
        hub.librarian.get_cto(t1).speaker_label
        == hub.librarian.get_cto(t3).speaker_label
        == "speaker_1"
    )


@pytest.mark.asyncio
async def test_start_turn_preserves_explicit_optional_fields(
    hub, session_id, full_content, submitter
):
    """When caller supplies optional fields, they must not be overwritten by defaults."""
    turn_id = await hub.start_turn(
        "conversation",
        full_content,
        submitter.token,
        session_id=session_id,
    )
    cto = hub.librarian.get_cto(turn_id)
    assert cto.speaker_role == "user"
    assert cto.speaker_label == "Tester"


@pytest.mark.asyncio
async def test_start_turn_missing_required_field_raises(hub, session_id, submitter):
    with pytest.raises(ValueError):
        await hub.start_turn(
            "conversation",
            {"speaker": {"id": "usr_x"}},  # missing 'text'
            submitter.token,
            session_id=session_id,
        )


@pytest.mark.asyncio
async def test_start_turn_missing_speaker_id_raises(hub, session_id, submitter):
    with pytest.raises(ValueError):
        await hub.start_turn(
            "conversation",
            {"speaker": {}, "text": "hello"},
            submitter.token,
            session_id=session_id,
        )


@pytest.mark.asyncio
async def test_start_turn_unknown_profile_raises(hub, session_id, submitter):
    with pytest.raises(KeyError):
        await hub.start_turn(
            "nonexistent_profile",
            {"anything": "goes"},
            submitter.token,
            session_id=session_id,
        )


@pytest.mark.asyncio
async def test_start_turn_strict_rejects_unknown_keys(session_id, persistence_purpose):
    hub = TTT.start(persistence_purpose, strict_profiles=True)
    submitter = RecordingPurpose()
    submitter.name = "submitter"
    await hub.start_purpose(submitter)
    with pytest.raises(ValueError, match="unknown keys"):
        await hub.start_turn(
            "conversation",
            {"speaker": {"id": "x"}, "text": "hi", "extra_key": "bad"},
            submitter.token,
            session_id=session_id,
        )


@pytest.mark.asyncio
async def test_start_turn_dispatches_cto_created_event(
    hub, session_id, minimal_content, submitter
):
    p = RecordingPurpose()
    await hub.start_purpose(p)
    await hub.start_turn(
        "conversation",
        minimal_content,
        submitter.token,
        session_id=session_id,
    )
    cto_events = [e for e in p.received if e.event_type == HubEventType.CTO_CREATED]
    assert len(cto_events) == 1
    assert cto_events[0].event_type == HubEventType.CTO_CREATED


@pytest.mark.asyncio
async def test_start_turn_event_carries_cto_index(
    hub, session_id, minimal_content, submitter
):
    p = RecordingPurpose()
    await hub.start_purpose(p)
    turn_id = await hub.start_turn(
        "conversation",
        minimal_content,
        submitter.token,
        session_id=session_id,
    )
    event = next(e for e in p.received if e.event_type == HubEventType.CTO_CREATED)
    cto_index = event.payload.as_dict()["cto_index"]
    assert cto_index["turn_id"] == str(turn_id)
    assert cto_index["session_id"] == str(session_id)


@pytest.mark.asyncio
async def test_start_turn_event_does_not_carry_full_cto(
    hub, session_id, minimal_content, submitter
):
    """Event payload must use CTOIndex, not full CTO content."""
    p = RecordingPurpose()
    await hub.start_purpose(p)
    await hub.start_turn(
        "conversation",
        minimal_content,
        submitter.token,
        session_id=session_id,
    )
    event = next(e for e in p.received if e.event_type == HubEventType.CTO_CREATED)
    payload = event.payload.as_dict()
    assert "content" not in payload
    assert "observations" not in payload
    assert "cto_index" in payload


@pytest.mark.asyncio
async def test_start_turn_each_turn_gets_unique_id(
    hub, session_id, minimal_content, submitter
):
    t1 = await hub.start_turn(
        "conversation",
        minimal_content,
        submitter.token,
        session_id=session_id,
    )
    t2 = await hub.start_turn(
        "conversation",
        minimal_content,
        submitter.token,
        session_id=session_id,
    )
    assert t1 != t2


@pytest.mark.asyncio
async def test_start_turn_does_not_dispatch_when_no_purposes(
    hub, session_id, minimal_content, submitter
):
    """start_turn with no registered purposes must not raise — just creates the CTO."""
    turn_id = await hub.start_turn(
        "conversation",
        minimal_content,
        submitter.token,
        session_id=session_id,
    )
    assert hub.librarian.get_cto(turn_id) is not None


# ---------------------------------------------------------------------------
# ttt.librarian.get_cto()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_librarian_get_cto_returns_none_for_unknown_turn_id(hub):
    assert hub.librarian.get_cto(uuid4()) is None


@pytest.mark.asyncio
async def test_librarian_get_cto_returns_latest_state_after_merge(
    hub, session_id, minimal_content, submitter
):
    """librarian.get_cto() must reflect the post-merge CTO, not the original."""
    purpose = NamedPurpose("tester")
    await hub.start_purpose(purpose)

    turn_id = await hub.start_turn(
        "conversation",
        minimal_content,
        submitter.token,
        session_id=session_id,
    )
    delta = Delta(
        delta_id=uuid4(),
        session_id=session_id,
        turn_id=turn_id,
        purpose_name=purpose.name,
        purpose_id=purpose.id,
        patch={"tags": ["important"]},
    )
    await hub.take_turn(_proposal_event_for(delta, purpose))
    cto = hub.librarian.get_cto(turn_id)
    assert "tester" in cto.observations
    assert any(obs["value"] == "important" for obs in cto.observations["tester"])


# ---------------------------------------------------------------------------
# _merge_delta() via hub.take_turn()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_delta_returns_event_id(
    hub, session_id, minimal_content, submitter
):
    purpose = NamedPurpose("annotator")
    await hub.start_purpose(purpose)

    turn_id = await hub.start_turn(
        "conversation",
        minimal_content,
        submitter.token,
        session_id=session_id,
    )
    delta = Delta(
        delta_id=uuid4(),
        session_id=session_id,
        turn_id=turn_id,
        purpose_name=purpose.name,
        purpose_id=purpose.id,
        patch={"result": ["ok"]},
    )
    event_id = await hub.take_turn(_proposal_event_for(delta, purpose))
    assert isinstance(event_id, UUID)


@pytest.mark.asyncio
async def test_merge_delta_appends_observations(
    hub, session_id, minimal_content, submitter
):
    purpose = NamedPurpose("annotator")
    await hub.start_purpose(purpose)

    turn_id = await hub.start_turn(
        "conversation",
        minimal_content,
        submitter.token,
        session_id=session_id,
    )
    d1 = Delta(
        delta_id=uuid4(),
        session_id=session_id,
        turn_id=turn_id,
        purpose_name=purpose.name,
        purpose_id=purpose.id,
        patch={"tags": ["a"]},
    )
    d2 = Delta(
        delta_id=uuid4(),
        session_id=session_id,
        turn_id=turn_id,
        purpose_name=purpose.name,
        purpose_id=purpose.id,
        patch={"tags": ["b"]},
    )
    await hub.take_turn(_proposal_event_for(d1, purpose))
    await hub.take_turn(_proposal_event_for(d2, purpose))
    obs = hub.librarian.get_cto(turn_id).observations[purpose.name]
    values = [o["value"] for o in obs]
    assert "a" in values
    assert "b" in values
    assert len(values) == 2


@pytest.mark.asyncio
async def test_merge_delta_does_not_overwrite_prior_observations(
    hub, session_id, minimal_content, submitter
):
    """Append-only: second merge must not erase observations from the first."""
    turn_id = await hub.start_turn(
        "conversation",
        minimal_content,
        submitter.token,
        session_id=session_id,
    )
    pid = uuid4()

    purpose = NamedPurpose("p")
    await hub.start_purpose(purpose)
    delta = Delta(
        delta_id=uuid4(),
        session_id=session_id,
        turn_id=turn_id,
        purpose_name=purpose.name,
        purpose_id=pid,
        patch={"x": [1]},
    )
    await hub.take_turn(_proposal_event_for(delta, purpose))

    purpose = NamedPurpose("p")
    await hub.start_purpose(purpose)

    delta = Delta(
        delta_id=uuid4(),
        session_id=session_id,
        turn_id=turn_id,
        purpose_name=purpose.name,
        purpose_id=pid,
        patch={"y": [2]},
    )
    await hub.take_turn(_proposal_event_for(delta, purpose))

    obs = hub.librarian.get_cto(turn_id).observations["p"]
    keys = [o["key"] for o in obs]
    assert "x" in keys
    assert "y" in keys


@pytest.mark.asyncio
async def test_merge_delta_namespaces_are_isolated(
    hub, session_id, minimal_content, submitter
):
    """Two Purposes writing to the same CTO must not interfere with each other."""
    turn_id = await hub.start_turn(
        "conversation",
        minimal_content,
        submitter.token,
        session_id=session_id,
    )
    purpose = NamedPurpose("p")
    await hub.start_purpose(purpose)

    delta = Delta(
        delta_id=uuid4(),
        session_id=session_id,
        turn_id=turn_id,
        purpose_name="purpose_a",
        purpose_id=purpose.id,
        patch={"score": [0.9]},
    )
    await hub.take_turn(_proposal_event_for(delta, purpose))

    purpose = NamedPurpose("p")
    await hub.start_purpose(purpose)

    delta = Delta(
        delta_id=uuid4(),
        session_id=session_id,
        turn_id=turn_id,
        purpose_name="purpose_b",
        purpose_id=purpose.id,
        patch={"score": [0.1]},
    )
    await hub.take_turn(_proposal_event_for(delta, purpose))

    obs = hub.librarian.get_cto(turn_id).observations
    assert "purpose_a" in obs
    assert "purpose_b" in obs
    assert obs["purpose_a"] != obs["purpose_b"]


@pytest.mark.asyncio
async def test_merge_delta_emits_delta_merged_event(
    hub, session_id, minimal_content, submitter
):
    p = RecordingPurpose()
    await hub.start_purpose(p)
    turn_id = await hub.start_turn(
        "conversation",
        minimal_content,
        submitter.token,
        session_id=session_id,
    )
    p.received.clear()  # ignore the cto_created event
    purpose = NamedPurpose("p")
    await hub.start_purpose(purpose)
    p.received.clear()  # ignore the purpose_started event

    delta = Delta(
        delta_id=uuid4(),
        session_id=session_id,
        turn_id=turn_id,
        purpose_name=purpose.name,
        purpose_id=purpose.id,
        patch={"x": ["v"]},
    )
    await hub.take_turn(_proposal_event_for(delta, purpose))
    delta_events = [e for e in p.received if e.event_type == HubEventType.DELTA_MERGED]
    assert len(delta_events) == 1
    assert delta_events[0].event_type == HubEventType.DELTA_MERGED


@pytest.mark.asyncio
async def test_merge_delta_event_payload_contains_cto_index(
    hub, session_id, minimal_content, submitter
):
    p = RecordingPurpose()
    await hub.start_purpose(p)
    turn_id = await hub.start_turn(
        "conversation",
        minimal_content,
        submitter.token,
        session_id=session_id,
    )
    p.received.clear()
    purpose = NamedPurpose("p")
    await hub.start_purpose(purpose)

    delta = Delta(
        delta_id=uuid4(),
        session_id=session_id,
        turn_id=turn_id,
        purpose_name=purpose.name,
        purpose_id=purpose.id,
        patch={"x": ["v"]},
    )
    await hub.take_turn(_proposal_event_for(delta, purpose))
    event = next(e for e in p.received if e.event_type == HubEventType.DELTA_MERGED)
    payload = event.payload.as_dict()
    assert "cto_index" in payload
    assert payload["cto_index"]["turn_id"] == str(turn_id)


@pytest.mark.asyncio
async def test_merge_delta_payload_has_no_stale_delta_field(
    hub, session_id, minimal_content, submitter
):
    """stale_delta was retired in v0.18 — must not appear in delta_merged payload."""
    p = RecordingPurpose()
    await hub.start_purpose(p)
    turn_id = await hub.start_turn(
        "conversation",
        minimal_content,
        submitter.token,
        session_id=session_id,
    )
    p.received.clear()
    purpose = NamedPurpose("p")
    await hub.start_purpose(purpose)

    delta = Delta(
        delta_id=uuid4(),
        session_id=session_id,
        turn_id=turn_id,
        purpose_name=purpose.name,
        purpose_id=purpose.id,
        patch={"x": ["v"]},
    )
    await hub.take_turn(_proposal_event_for(delta, purpose))
    event = next(e for e in p.received if e.event_type == HubEventType.DELTA_MERGED)
    payload = event.payload.as_dict()
    assert "stale_delta" not in payload


@pytest.mark.asyncio
async def test_merge_delta_unknown_turn_id_raises(hub, session_id, submitter):
    purpose = NamedPurpose("p")
    await hub.start_purpose(purpose)

    delta = Delta(
        delta_id=uuid4(),
        session_id=session_id,
        turn_id=uuid4(),
        purpose_name=purpose.name,
        purpose_id=purpose.id,
        patch={"x": ["v"]},
    )

    with pytest.raises(KeyError, match="_merge_delta: unknown turn_id"):
        await hub.take_turn(_proposal_event_for(delta, purpose))


@pytest.mark.asyncio
async def test_merge_delta_non_list_patch_value_raises(
    hub, session_id, minimal_content, submitter
):
    purpose = NamedPurpose("p")
    await hub.start_purpose(purpose)

    turn_id = await hub.start_turn(
        "conversation",
        minimal_content,
        submitter.token,
        session_id=session_id,
    )

    delta = Delta(
        delta_id=uuid4(),
        session_id=session_id,
        turn_id=turn_id,
        purpose_name=purpose.name,
        purpose_id=purpose.id,
        patch={"bad": "not_a_list"},
    )

    with pytest.raises(ValueError, match="must be a list"):
        await hub.take_turn(_proposal_event_for(delta, purpose))


# ---------------------------------------------------------------------------
# _multicast() — per-recipient token stamping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multicast_stamps_correct_token_per_recipient(
    hub, session_id, minimal_content, submitter
):
    """Each Purpose must receive an event with its own token, not another's."""
    p1 = NamedPurpose("alpha")
    p2 = NamedPurpose("beta")
    await hub.start_purpose(p1)
    await hub.start_purpose(p2)

    await hub.start_turn(
        "conversation",
        minimal_content,
        submitter.token,
        session_id=session_id,
    )

    assert p1.received[0].hub_token == p1.token
    assert p2.received[0].hub_token == p2.token
    assert p1.received[0].hub_token != p2.received[0].hub_token
    assert p1.received[0].downlink_signature == p1.downlink_signature
    assert p2.received[0].downlink_signature == p2.downlink_signature
    assert p1.received[0].downlink_signature != p2.received[0].downlink_signature


@pytest.mark.asyncio
async def test_multicast_all_purposes_receive_event(
    hub, session_id, minimal_content, submitter
):
    purposes = [NamedPurpose(f"p{i}") for i in range(4)]
    for p in purposes:
        await hub.start_purpose(p)

    await hub.start_turn(
        "conversation",
        minimal_content,
        submitter.token,
        session_id=session_id,
    )

    for p in purposes:
        cto_events = [e for e in p.received if e.event_type == HubEventType.CTO_CREATED]
        assert len(cto_events) == 1


@pytest.mark.asyncio
async def test_multicast_token_from_one_purpose_rejected_by_another(
    hub, session_id, minimal_content, submitter
):
    """Feeding one Purpose's token-stamped event directly to another must raise."""
    p1 = NamedPurpose("alpha")
    p2 = NamedPurpose("beta")
    await hub.start_purpose(p1)
    await hub.start_purpose(p2)

    await hub.start_turn(
        "conversation",
        minimal_content,
        submitter.token,
        session_id=session_id,
    )

    # p1's event carries p1's token — p2 must reject it
    event_for_p1 = p1.received[0]
    with pytest.raises(UnauthorizedDispatchError):
        await p2.take_turn(event_for_p1)
