"""Tests for BasePurpose routing validation."""

from __future__ import annotations

from uuid import uuid4

import pytest
from conftest import RecordingPurpose

from turnturnturn.errors import (
    InvalidDownlinkSignatureError,
    UnauthorizedDispatchError,
    UnboundPurposeError,
)
from turnturnturn.events import EmptyPayload, HubEvent, HubEventType


def _make_event(
    *,
    hub_token: str | None = None,
    downlink_signature: str | None = None,
) -> HubEvent:
    return HubEvent(
        event_type=HubEventType.CTO_STARTED,
        event_id=uuid4(),
        created_at_ms=0,
        payload=EmptyPayload(),
        hub_token=hub_token,
        downlink_signature=downlink_signature,
    )


def test_token_property_none_before_assignment():
    p = RecordingPurpose()
    assert p.token is None


def test_downlink_signature_property_none_before_assignment():
    p = RecordingPurpose()
    assert p.downlink_signature is None


def test_assign_token_sets_token():
    p = RecordingPurpose()
    p._assign_token("abc123")
    assert p.token == "abc123"


def test_assign_downlink_signature_sets_signature():
    p = RecordingPurpose()
    p._assign_downlink_signature("sig123")
    assert p.downlink_signature == "sig123"


@pytest.mark.asyncio
async def test_take_turn_raises_unbound_when_no_route_credentials():
    p = RecordingPurpose()
    event = _make_event(hub_token=None, downlink_signature=None)
    with pytest.raises(UnboundPurposeError):
        await p.take_turn(event)


@pytest.mark.asyncio
async def test_take_turn_raises_unauthorized_on_wrong_token():
    p = RecordingPurpose()
    p._assign_token("correct_token")
    p._assign_downlink_signature("sig")
    event = _make_event(hub_token="wrong_token", downlink_signature="sig")
    with pytest.raises(UnauthorizedDispatchError):
        await p.take_turn(event)


@pytest.mark.asyncio
async def test_take_turn_raises_invalid_downlink_signature_on_wrong_signature():
    p = RecordingPurpose()
    p._assign_token("tok")
    p._assign_downlink_signature("correct_sig")
    event = _make_event(hub_token="tok", downlink_signature="wrong_sig")
    with pytest.raises(InvalidDownlinkSignatureError):
        await p.take_turn(event)


@pytest.mark.asyncio
async def test_take_turn_calls_handle_event_on_valid_token():
    p = RecordingPurpose()
    p._assign_token("good_token")
    p._assign_downlink_signature("good_sig")
    event = _make_event(hub_token="good_token", downlink_signature="good_sig")
    await p.take_turn(event)
    assert len(p.received) == 1


@pytest.mark.asyncio
async def test_take_turn_raises_unauthorized_when_token_is_none_after_assignment():
    """Even hub_token=None is rejected once a Purpose has been assigned a token."""
    p = RecordingPurpose()
    p._assign_token("real_token")
    p._assign_downlink_signature("sig")
    event = _make_event(hub_token=None, downlink_signature="sig")
    with pytest.raises(UnauthorizedDispatchError):
        await p.take_turn(event)


@pytest.mark.asyncio
async def test_unauthorized_error_message_contains_purpose_name():
    p = RecordingPurpose()
    p._assign_token("tok")
    p._assign_downlink_signature("sig")
    event = _make_event(hub_token="wrong", downlink_signature="sig")
    with pytest.raises(UnauthorizedDispatchError, match="recording"):
        await p.take_turn(event)
