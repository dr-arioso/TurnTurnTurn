"""Tests for temporary historian persistence seams."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from conftest import RecordingPurpose

from turnturnturn import TTT, InMemoryHistorian, JsonlHistorian
from turnturnturn.delta import Delta
from turnturnturn.events import (
    DeltaProposalEvent,
    DeltaProposalPayload,
    PurposeEventType,
)


def _proposal_event_for(delta: Delta, purpose: RecordingPurpose) -> DeltaProposalEvent:
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
async def test_start_turn_persists_hub_event_and_cto_snapshot(
    session_id, minimal_content
):
    historian = InMemoryHistorian()
    hub = TTT.start(historian=historian)

    turn_id = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )

    assert len(historian.events) == 1
    assert historian.events[0]["record_type"] == "hub_event"
    assert historian.events[0]["event_type"] == "cto_created"
    assert historian.events[0]["turn_id"] == str(turn_id)

    assert len(historian.cto_snapshots) == 1
    assert historian.cto_snapshots[0]["record_type"] == "cto_snapshot"
    assert historian.cto_snapshots[0]["turn_id"] == str(turn_id)


@pytest.mark.asyncio
async def test_take_turn_persists_accepted_purpose_event_and_merge_outputs(
    session_id, minimal_content
):
    historian = InMemoryHistorian()
    hub = TTT.start(historian=historian)

    purpose = RecordingPurpose()
    await hub.start_purpose(purpose)

    turn_id = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )

    delta = Delta(
        delta_id=uuid4(),
        session_id=session_id,
        turn_id=turn_id,
        purpose_name=purpose.name,
        purpose_id=purpose.id,
        patch={"tags": ["important"]},
    )
    event = _proposal_event_for(delta, purpose)

    await hub.take_turn(event)

    assert [record["event_type"] for record in historian.events] == [
        "cto_created",
        "delta_proposal",
        "delta_merged",
    ]
    assert len(historian.cto_snapshots) == 2
    assert (
        historian.cto_snapshots[-1]["observations"][purpose.name][0]["value"]
        == "important"
    )


@pytest.mark.asyncio
async def test_invalid_purpose_event_is_not_persisted(session_id, minimal_content):
    historian = InMemoryHistorian()
    hub = TTT.start(historian=historian)

    purpose = RecordingPurpose()
    await hub.start_purpose(purpose)

    turn_id = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )

    delta = Delta(
        delta_id=uuid4(),
        session_id=session_id,
        turn_id=turn_id,
        purpose_name=purpose.name,
        purpose_id=purpose.id,
        patch={"tags": ["important"]},
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

    with pytest.raises(Exception):
        await hub.take_turn(event)

    assert [record["event_type"] for record in historian.events] == ["cto_created"]
    assert len(historian.cto_snapshots) == 1


@pytest.mark.asyncio
async def test_jsonl_historian_writes_files(
    tmp_path: Path, session_id, minimal_content
):
    events_path = tmp_path / "events.jsonl"
    snapshots_path = tmp_path / "cto_snapshots.jsonl"
    print(snapshots_path)
    hub = TTT.start(
        historian=JsonlHistorian(
            events_path=events_path,
            cto_snapshots_path=snapshots_path,
        )
    )

    await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )

    assert events_path.exists()
    assert snapshots_path.exists()

    event_rows = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
    ]
    snapshot_rows = [
        json.loads(line)
        for line in snapshots_path.read_text(encoding="utf-8").splitlines()
    ]

    assert event_rows[0]["event_type"] == "cto_created"
    assert snapshot_rows[0]["record_type"] == "cto_snapshot"
