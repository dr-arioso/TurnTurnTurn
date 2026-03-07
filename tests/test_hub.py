"""Tests for the TTT hub runtime (hub.py).

Coverage areas:
  - TTT.create() — profile loading, strict flag
  - register_purpose() — token assignment, re-registration
  - start_turn() — CTO creation, profile validation, event emission, dispatch
  - merge_delta() — append-only merge, unknown turn_id, bad patch shape
  - get_cto() — read path, returns None for unknown turn_id
  - _multicast() — per-recipient token stamping, all registered purposes receive event
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from conftest import NamedPurpose, RecordingPurpose

from turnturnturn import CTO, TTT, Delta
from turnturnturn.errors import UnauthorizedDispatchError
from turnturnturn.events import HubEventType

# ---------------------------------------------------------------------------
# TTT.create()
# ---------------------------------------------------------------------------


def test_create_returns_ttt_instance():
    hub = TTT.create()
    assert isinstance(hub, TTT)


def test_create_loads_conversation_profile():
    """TTT.create() must register the conversation profile so start_turn works."""
    hub = TTT.create()
    # If the profile is missing, start_turn raises KeyError — so a successful
    # call here proves the profile is registered.
    # (async assertion is in test_start_turn_* tests; this is a smoke check)
    assert hub is not None


def test_create_strict_profiles_flag():
    hub = TTT.create(strict_profiles=True)
    assert hub.strict_profiles is True


def test_create_strict_profiles_default_false():
    hub = TTT.create()
    assert hub.strict_profiles is False


# ---------------------------------------------------------------------------
# register_purpose()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_purpose_assigns_token(hub):
    p = RecordingPurpose()
    assert p.token is None  # unbound before registration
    await hub.register_purpose(p)
    assert p.token is not None
    assert isinstance(p.token, str)
    assert len(p.token) > 0


@pytest.mark.asyncio
async def test_register_purpose_stores_registration(hub):
    p = RecordingPurpose()
    await hub.register_purpose(p)
    assert p.id in hub.registrations


@pytest.mark.asyncio
async def test_register_multiple_purposes_each_gets_unique_token(hub):
    p1 = RecordingPurpose()
    p2 = RecordingPurpose()
    await hub.register_purpose(p1)
    await hub.register_purpose(p2)
    assert p1.token != p2.token


@pytest.mark.asyncio
async def test_reregister_purpose_issues_new_token(hub):
    p = RecordingPurpose()
    await hub.register_purpose(p)
    first_token = p.token
    await hub.register_purpose(p)
    assert p.token != first_token


@pytest.mark.asyncio
async def test_register_raw_protocol_purpose_no_token(hub):
    """A bare PurposeProtocol implementor (test double) gets registered without a token."""

    class RawPurpose:
        name = "raw"
        id = uuid4()
        token = None
        received = []

        async def take_turn(self, event):
            self.received.append(event)

    raw = RawPurpose()
    await hub.register_purpose(raw)
    assert raw.id in hub.registrations
    assert hub.registrations[raw.id].token is None


# ---------------------------------------------------------------------------
# start_turn()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_turn_returns_uuid(hub, session_id, minimal_content):
    turn_id = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )
    assert isinstance(turn_id, UUID)


@pytest.mark.asyncio
async def test_start_turn_stores_cto(hub, session_id, minimal_content):
    turn_id = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )
    cto = hub.get_cto(turn_id)
    assert cto is not None
    assert isinstance(cto, CTO)
    assert cto.turn_id == turn_id
    assert cto.session_id == session_id


@pytest.mark.asyncio
async def test_start_turn_cto_content_profile_dict(hub, session_id, minimal_content):
    """content_profile on the created CTO must be {"id": ..., "version": ...}."""
    turn_id = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )
    cto = hub.get_cto(turn_id)
    assert cto.content_profile == {"id": "conversation", "version": 1}


@pytest.mark.asyncio
async def test_start_turn_applies_speaker_role_default(hub, session_id):
    turn_id = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content={"speaker": {"id": "usr_x"}, "text": "hi"},
    )
    cto = hub.get_cto(turn_id)
    assert cto.speaker_role == "speaker"


@pytest.mark.asyncio
async def test_start_turn_applies_speaker_label_default(hub, session_id):
    turn_id = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content={"speaker": {"id": "usr_x"}, "text": "hi"},
    )
    cto = hub.get_cto(turn_id)
    assert cto.speaker_label == "speaker_1"


@pytest.mark.asyncio
async def test_start_turn_speaker_label_ordinal_increments(hub, session_id):
    """Each distinct speaker.id within a session gets a new ordinal."""
    await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content={"speaker": {"id": "a"}, "text": "first"},
    )
    t2 = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content={"speaker": {"id": "b"}, "text": "second"},
    )
    cto2 = hub.get_cto(t2)
    assert cto2.speaker_label == "speaker_2"


@pytest.mark.asyncio
async def test_start_turn_same_speaker_same_ordinal(hub, session_id):
    """The same speaker.id always resolves to the same label within a session."""
    t1 = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content={"speaker": {"id": "alice"}, "text": "turn 1"},
    )
    await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content={"speaker": {"id": "bob"}, "text": "turn 2"},
    )
    t3 = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content={"speaker": {"id": "alice"}, "text": "turn 3"},
    )
    assert hub.get_cto(t1).speaker_label == hub.get_cto(t3).speaker_label == "speaker_1"


@pytest.mark.asyncio
async def test_start_turn_preserves_explicit_optional_fields(
    hub, session_id, full_content
):
    """When caller supplies optional fields, they must not be overwritten by defaults."""
    turn_id = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=full_content,
    )
    cto = hub.get_cto(turn_id)
    assert cto.speaker_role == "user"
    assert cto.speaker_label == "Tester"


@pytest.mark.asyncio
async def test_start_turn_missing_required_field_raises(hub, session_id):
    with pytest.raises(ValueError):
        await hub.start_turn(
            session_id=session_id,
            content_profile="conversation",
            content={"speaker": {"id": "usr_x"}},  # missing 'text'
        )


@pytest.mark.asyncio
async def test_start_turn_missing_speaker_id_raises(hub, session_id):
    with pytest.raises(ValueError):
        await hub.start_turn(
            session_id=session_id,
            content_profile="conversation",
            content={"speaker": {}, "text": "hello"},
        )


@pytest.mark.asyncio
async def test_start_turn_unknown_profile_raises(hub, session_id):
    with pytest.raises(KeyError):
        await hub.start_turn(
            session_id=session_id,
            content_profile="nonexistent_profile",
            content={"anything": "goes"},
        )


@pytest.mark.asyncio
async def test_start_turn_strict_rejects_unknown_keys(session_id):
    hub = TTT.create(strict_profiles=True)
    with pytest.raises(ValueError, match="unknown keys"):
        await hub.start_turn(
            session_id=session_id,
            content_profile="conversation",
            content={"speaker": {"id": "x"}, "text": "hi", "extra_key": "bad"},
        )


@pytest.mark.asyncio
async def test_start_turn_dispatches_cto_created_event(
    hub, session_id, minimal_content
):
    p = RecordingPurpose()
    await hub.register_purpose(p)
    await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )
    assert len(p.received) == 1
    assert p.received[0].event_type == HubEventType.CTO_CREATED


@pytest.mark.asyncio
async def test_start_turn_event_carries_cto_index(hub, session_id, minimal_content):
    p = RecordingPurpose()
    await hub.register_purpose(p)
    turn_id = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )
    event = p.received[0]
    cto_index = event.payload["cto_index"]
    assert cto_index["turn_id"] == str(turn_id)
    assert cto_index["session_id"] == str(session_id)


@pytest.mark.asyncio
async def test_start_turn_event_does_not_carry_full_cto(
    hub, session_id, minimal_content
):
    """Event payload must use CTOIndex, not full CTO content."""
    p = RecordingPurpose()
    await hub.register_purpose(p)
    await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )
    payload = p.received[0].payload
    assert "content" not in payload
    assert "observations" not in payload
    assert "cto_index" in payload


@pytest.mark.asyncio
async def test_start_turn_each_turn_gets_unique_id(hub, session_id, minimal_content):
    t1 = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )
    t2 = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )
    assert t1 != t2


@pytest.mark.asyncio
async def test_start_turn_does_not_dispatch_when_no_purposes(
    hub, session_id, minimal_content
):
    """start_turn with no registered purposes must not raise — just creates the CTO."""
    turn_id = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )
    assert hub.get_cto(turn_id) is not None


# ---------------------------------------------------------------------------
# get_cto()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_cto_returns_none_for_unknown_turn_id(hub):
    assert hub.get_cto(uuid4()) is None


@pytest.mark.asyncio
async def test_get_cto_returns_latest_state_after_merge(
    hub, session_id, minimal_content
):
    """get_cto() must reflect the post-merge CTO, not the original."""
    turn_id = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )
    delta = Delta(
        delta_id=uuid4(),
        session_id=session_id,
        turn_id=turn_id,
        purpose_name="tester",
        purpose_id=uuid4(),
        patch={"tags": ["important"]},
    )
    await hub.merge_delta(delta)
    cto = hub.get_cto(turn_id)
    assert "tester" in cto.observations
    assert any(obs["value"] == "important" for obs in cto.observations["tester"])


# ---------------------------------------------------------------------------
# merge_delta()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_delta_returns_event_id(hub, session_id, minimal_content):
    turn_id = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )
    delta = Delta(
        delta_id=uuid4(),
        session_id=session_id,
        turn_id=turn_id,
        purpose_name="p",
        purpose_id=uuid4(),
        patch={"result": ["ok"]},
    )
    event_id = await hub.merge_delta(delta)
    assert isinstance(event_id, UUID)


@pytest.mark.asyncio
async def test_merge_delta_appends_observations(hub, session_id, minimal_content):
    turn_id = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )
    pid = uuid4()
    d1 = Delta(
        delta_id=uuid4(),
        session_id=session_id,
        turn_id=turn_id,
        purpose_name="annotator",
        purpose_id=pid,
        patch={"tags": ["a"]},
    )
    d2 = Delta(
        delta_id=uuid4(),
        session_id=session_id,
        turn_id=turn_id,
        purpose_name="annotator",
        purpose_id=pid,
        patch={"tags": ["b"]},
    )
    await hub.merge_delta(d1)
    await hub.merge_delta(d2)
    obs = hub.get_cto(turn_id).observations["annotator"]
    values = [o["value"] for o in obs]
    assert "a" in values
    assert "b" in values
    assert len(values) == 2


@pytest.mark.asyncio
async def test_merge_delta_does_not_overwrite_prior_observations(
    hub, session_id, minimal_content
):
    """Append-only: second merge must not erase observations from the first."""
    turn_id = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )
    pid = uuid4()
    await hub.merge_delta(
        Delta(
            delta_id=uuid4(),
            session_id=session_id,
            turn_id=turn_id,
            purpose_name="p",
            purpose_id=pid,
            patch={"x": [1]},
        )
    )
    await hub.merge_delta(
        Delta(
            delta_id=uuid4(),
            session_id=session_id,
            turn_id=turn_id,
            purpose_name="p",
            purpose_id=pid,
            patch={"y": [2]},
        )
    )
    obs = hub.get_cto(turn_id).observations["p"]
    keys = [o["key"] for o in obs]
    assert "x" in keys
    assert "y" in keys


@pytest.mark.asyncio
async def test_merge_delta_namespaces_are_isolated(hub, session_id, minimal_content):
    """Two Purposes writing to the same CTO must not interfere with each other."""
    turn_id = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )
    await hub.merge_delta(
        Delta(
            delta_id=uuid4(),
            session_id=session_id,
            turn_id=turn_id,
            purpose_name="purpose_a",
            purpose_id=uuid4(),
            patch={"score": [0.9]},
        )
    )
    await hub.merge_delta(
        Delta(
            delta_id=uuid4(),
            session_id=session_id,
            turn_id=turn_id,
            purpose_name="purpose_b",
            purpose_id=uuid4(),
            patch={"score": [0.1]},
        )
    )
    obs = hub.get_cto(turn_id).observations
    assert "purpose_a" in obs
    assert "purpose_b" in obs
    assert obs["purpose_a"] != obs["purpose_b"]


@pytest.mark.asyncio
async def test_merge_delta_emits_delta_merged_event(hub, session_id, minimal_content):
    p = RecordingPurpose()
    await hub.register_purpose(p)
    turn_id = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )
    p.received.clear()  # ignore the cto_created event
    await hub.merge_delta(
        Delta(
            delta_id=uuid4(),
            session_id=session_id,
            turn_id=turn_id,
            purpose_name="p",
            purpose_id=uuid4(),
            patch={"x": ["v"]},
        )
    )
    assert len(p.received) == 1
    assert p.received[0].event_type == HubEventType.DELTA_MERGED


@pytest.mark.asyncio
async def test_merge_delta_event_payload_contains_cto_index(
    hub, session_id, minimal_content
):
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
            patch={"x": ["v"]},
        )
    )
    payload = p.received[0].payload
    assert "cto_index" in payload
    assert payload["cto_index"]["turn_id"] == str(turn_id)


@pytest.mark.asyncio
async def test_merge_delta_unknown_turn_id_raises(hub, session_id):
    with pytest.raises(KeyError):
        await hub.merge_delta(
            Delta(
                delta_id=uuid4(),
                session_id=session_id,
                turn_id=uuid4(),
                purpose_name="p",
                purpose_id=uuid4(),
                patch={"x": ["v"]},
            )
        )


@pytest.mark.asyncio
async def test_merge_delta_non_list_patch_value_raises(
    hub, session_id, minimal_content
):
    turn_id = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )
    with pytest.raises(ValueError, match="must be a list"):
        await hub.merge_delta(
            Delta(
                delta_id=uuid4(),
                session_id=session_id,
                turn_id=turn_id,
                purpose_name="p",
                purpose_id=uuid4(),
                patch={"bad": "not_a_list"},
            )
        )


# ---------------------------------------------------------------------------
# _multicast() — per-recipient token stamping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multicast_stamps_correct_token_per_recipient(
    hub, session_id, minimal_content
):
    """Each Purpose must receive an event with its own token, not another's."""
    p1 = NamedPurpose("alpha")
    p2 = NamedPurpose("beta")
    await hub.register_purpose(p1)
    await hub.register_purpose(p2)

    await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )

    assert p1.received[0].hub_token == p1.token
    assert p2.received[0].hub_token == p2.token
    assert p1.received[0].hub_token != p2.received[0].hub_token


@pytest.mark.asyncio
async def test_multicast_all_purposes_receive_event(hub, session_id, minimal_content):
    purposes = [NamedPurpose(f"p{i}") for i in range(4)]
    for p in purposes:
        await hub.register_purpose(p)

    await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )

    for p in purposes:
        assert len(p.received) == 1


@pytest.mark.asyncio
async def test_multicast_token_from_one_purpose_rejected_by_another(
    hub, session_id, minimal_content
):
    """Feeding one Purpose's token-stamped event directly to another must raise."""
    p1 = NamedPurpose("alpha")
    p2 = NamedPurpose("beta")
    await hub.register_purpose(p1)
    await hub.register_purpose(p2)

    await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )

    # p1's event carries p1's token — p2 must reject it
    event_for_p1 = p1.received[0]
    with pytest.raises(UnauthorizedDispatchError):
        await p2.take_turn(event_for_p1)
