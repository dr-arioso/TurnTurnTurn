"""Tests for Purpose-originated hub ingress via hub.take_turn()."""

from __future__ import annotations

from uuid import uuid4

import pytest
from conftest import RecordingPurpose

from turnturnturn import CTO, cto_json_document
from turnturnturn.delta import Delta
from turnturnturn.errors import UnauthorizedDispatchError, UnknownEventTypeError
from turnturnturn.events import (
    CTOImportedEvent,
    CTOImportedPayload,
    DeltaProposalEvent,
    DeltaProposalPayload,
    PurposeEventType,
)


def _make_delta(*, session_id, turn_id, purpose_name, purpose_id, patch):
    return Delta(
        delta_id=uuid4(),
        session_id=session_id,
        turn_id=turn_id,
        purpose_name=purpose_name,
        purpose_id=purpose_id,
        patch=patch,
    )


def _make_delta_proposal_event(*, purpose, delta):
    return DeltaProposalEvent(
        event_type=PurposeEventType.DELTA_PROPOSAL,
        event_id=uuid4(),
        created_at_ms=0,
        purpose_id=purpose.id,
        purpose_name=purpose.name,
        hub_token=purpose.token,
        payload=DeltaProposalPayload(delta=delta),
    )


@pytest.mark.asyncio
async def test_take_turn_valid_delta_proposal_updates_observations(
    hub, session_id, minimal_content, submitter
):
    purpose = RecordingPurpose()
    await hub.start_purpose(purpose)

    turn_id = await hub.start_turn(
        "conversation",
        minimal_content,
        submitter.token,
        session_id=session_id,
    )

    delta = _make_delta(
        session_id=session_id,
        turn_id=turn_id,
        purpose_name=purpose.name,
        purpose_id=purpose.id,
        patch={"tags": ["important"]},
    )
    event = _make_delta_proposal_event(purpose=purpose, delta=delta)

    await hub.take_turn(event)

    cto = hub.librarian.get_cto(turn_id)
    assert purpose.name in cto.observations
    assert any(obs["value"] == "important" for obs in cto.observations[purpose.name])


@pytest.mark.asyncio
async def test_take_turn_wrong_token_raises(
    hub, session_id, minimal_content, submitter
):
    purpose = RecordingPurpose()
    await hub.start_purpose(purpose)

    turn_id = await hub.start_turn(
        "conversation",
        minimal_content,
        submitter.token,
        session_id=session_id,
    )

    delta = _make_delta(
        session_id=session_id,
        turn_id=turn_id,
        purpose_name=purpose.name,
        purpose_id=purpose.id,
        patch={"x": ["v"]},
    )

    event = DeltaProposalEvent(
        event_type=PurposeEventType.DELTA_PROPOSAL,
        event_id=uuid4(),
        created_at_ms=0,
        purpose_id=purpose.id,
        purpose_name=purpose.name,
        hub_token="wrong_token",
        payload=DeltaProposalPayload(delta=delta),
    )

    with pytest.raises(UnauthorizedDispatchError):
        await hub.take_turn(event)


@pytest.mark.asyncio
async def test_take_turn_mismatched_purpose_name_raises(
    hub, session_id, minimal_content, submitter
):
    purpose = RecordingPurpose()
    await hub.start_purpose(purpose)

    turn_id = await hub.start_turn(
        "conversation",
        minimal_content,
        submitter.token,
        session_id=session_id,
    )

    delta = _make_delta(
        session_id=session_id,
        turn_id=turn_id,
        purpose_name=purpose.name,
        purpose_id=purpose.id,
        patch={"x": ["v"]},
    )

    event = DeltaProposalEvent(
        event_type=PurposeEventType.DELTA_PROPOSAL,
        event_id=uuid4(),
        created_at_ms=0,
        purpose_id=purpose.id,
        purpose_name="not_recording",
        hub_token=purpose.token,
        payload=DeltaProposalPayload(delta=delta),
    )

    with pytest.raises(UnauthorizedDispatchError):
        await hub.take_turn(event)


@pytest.mark.asyncio
async def test_take_turn_unknown_event_type_raises(
    hub, session_id, minimal_content, submitter
):
    purpose = RecordingPurpose()
    await hub.start_purpose(purpose)

    await hub.start_turn(
        "conversation",
        minimal_content,
        submitter.token,
        session_id=session_id,
    )

    class UnknownEvent:
        event_type = "unknown.event"
        event_id = uuid4()
        created_at_ms = 0
        purpose_id = purpose.id
        purpose_name = purpose.name
        hub_token = purpose.token

        class _Payload:
            def as_dict(self):
                return {}

        payload = _Payload()

    with pytest.raises(UnknownEventTypeError):
        await hub.take_turn(UnknownEvent())


@pytest.mark.asyncio
async def test_take_turn_rejects_cto_imported_from_non_persistence_purpose(hub):
    purpose = RecordingPurpose()
    await hub.start_purpose(purpose)
    session_id = uuid4()
    document = cto_json_document(
        CTO(
            turn_id=uuid4(),
            session_id=uuid4(),
            created_at_ms=1234,
            content_profile={"id": "conversation", "version": 1},
            content={"speaker": {"id": "usr_test"}, "text": "imported"},
        )
    )
    event = CTOImportedEvent(
        purpose_id=purpose.id,
        purpose_name=purpose.name,
        hub_token=purpose.token,
        session_id=session_id,
        payload=CTOImportedPayload(
            session_id=str(session_id),
            source_kind="cto_json",
            source_locator="/tmp/import.json",
            source_content_hash="abc123",
            requested_by_purpose_id=str(purpose.id),
            requested_by_purpose_name=purpose.name,
            cto_json=document,
        ),
    )

    with pytest.raises(UnauthorizedDispatchError):
        await hub.take_turn(event)
