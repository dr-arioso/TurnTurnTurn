"""Tests for BasePurpose (base_purpose.py).

Coverage areas:
  - Initial unbound state
  - _assign_token() — guards against empty token
  - token property — None when unbound, string after assignment
  - take_turn() — raises UnboundPurposeError when unregistered
  - take_turn() — raises UnauthorizedDispatchError on token mismatch
  - take_turn() — calls _handle_event() on valid token
  - Subclass contract — _handle_event is abstract; take_turn must not be overridden
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from conftest import RecordingPurpose

from turnturnturn import BasePurpose
from turnturnturn.errors import UnauthorizedDispatchError, UnboundPurposeError
from turnturnturn.events import HubEvent, HubEventType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(hub_token: str | None = None) -> HubEvent:
    """Construct a minimal HubEvent for dispatch tests."""
    return HubEvent(
        event_type=HubEventType.CTO_CREATED,
        event_id=uuid4(),
        created_at_ms=0,
        hub_token=hub_token,
    )


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------


def test_base_purpose_token_is_none_before_registration():
    p = RecordingPurpose()
    assert p.token is None


def test_base_purpose_is_abstract():
    """BasePurpose cannot be instantiated directly — _handle_event is abstract."""
    with pytest.raises(TypeError):
        BasePurpose()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# _assign_token()
# ---------------------------------------------------------------------------


def test_assign_token_sets_token():
    p = RecordingPurpose()
    p._assign_token("abc123")
    assert p.token == "abc123"


def test_assign_token_rejects_empty_string():
    p = RecordingPurpose()
    with pytest.raises(ValueError):
        p._assign_token("")


def test_assign_token_can_be_reassigned():
    """Re-registration issues a new token — _assign_token must accept a second call."""
    p = RecordingPurpose()
    p._assign_token("first")
    p._assign_token("second")
    assert p.token == "second"


# ---------------------------------------------------------------------------
# take_turn() — error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_take_turn_raises_unbound_when_no_token():
    p = RecordingPurpose()
    event = _make_event(hub_token=None)
    with pytest.raises(UnboundPurposeError):
        await p.take_turn(event)


@pytest.mark.asyncio
async def test_take_turn_raises_unauthorized_on_wrong_token():
    p = RecordingPurpose()
    p._assign_token("correct_token")
    event = _make_event(hub_token="wrong_token")
    with pytest.raises(UnauthorizedDispatchError):
        await p.take_turn(event)


@pytest.mark.asyncio
async def test_take_turn_raises_unauthorized_when_token_is_none_after_assignment():
    """Even hub_token=None is rejected once a Purpose has been assigned a token."""
    p = RecordingPurpose()
    p._assign_token("real_token")
    event = _make_event(hub_token=None)
    with pytest.raises(UnauthorizedDispatchError):
        await p.take_turn(event)


# ---------------------------------------------------------------------------
# take_turn() — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_take_turn_calls_handle_event_on_valid_token():
    p = RecordingPurpose()
    p._assign_token("good_token")
    event = _make_event(hub_token="good_token")
    await p.take_turn(event)
    assert len(p.received) == 1
    assert p.received[0] is event


@pytest.mark.asyncio
async def test_take_turn_accumulates_multiple_events():
    p = RecordingPurpose()
    p._assign_token("tok")
    for _ in range(3):
        await p.take_turn(_make_event(hub_token="tok"))
    assert len(p.received) == 3


# ---------------------------------------------------------------------------
# Error messages
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unbound_error_message_contains_purpose_name():
    p = RecordingPurpose()
    event = _make_event()
    with pytest.raises(UnboundPurposeError, match="recording"):
        await p.take_turn(event)


@pytest.mark.asyncio
async def test_unauthorized_error_message_contains_purpose_name():
    p = RecordingPurpose()
    p._assign_token("tok")
    event = _make_event(hub_token="wrong")
    with pytest.raises(UnauthorizedDispatchError, match="recording"):
        await p.take_turn(event)
