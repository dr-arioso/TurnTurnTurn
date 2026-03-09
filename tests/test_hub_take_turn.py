"""Tests for Purpose-originated hub ingress via hub.take_turn()."""

from __future__ import annotations

from uuid import uuid4

import pytest
from conftest import RecordingPurpose

from turnturnturn.delta import Delta
from turnturnturn.errors import UnauthorizedDispatchError
from turnturnturn.events import (
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
        started_at_ms=0,
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
        started_at_ms=0,
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
        started_at_ms=0,
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
