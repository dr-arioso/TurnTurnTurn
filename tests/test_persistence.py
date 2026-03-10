"""
Tests for the persistence architecture (Commit 9).

Coverage areas:

TTT.start() — persistence_purpose contract
  - TypeError if persistence_purpose missing
  - TypeError if persistence_purpose does not satisfy CTOPersistencePurposeProtocol
  - UserWarning if is_durable=False
  - No warning if is_durable=True

session_started event
  - Written to persistence Purpose before any other event
  - Carries hub_id, ttt_version, persister_name, persister_id,
    persister_is_durable, strict_profiles fields
  - Never delivered to domain Purposes via multicast

PurposeStartedPayload on start_purpose()
  - purpose_started event persisted after start_purpose()
  - Carries purpose_name, purpose_id, is_persistence_purpose=False
    for domain Purposes

Persistence-first routing (_multicast phase order)
  - write_event() called before domain Purpose receives event
  - PersistenceFailureError raised if write_event() raises, halting delivery
  - Domain Purpose does not receive event when persistence fails

hub_token required for start_turn()
  - UnauthorizedDispatchError if hub_token is invalid
  - No CTO created on auth failure
  - Valid token succeeds; CTO is created

hub-minted session_id
  - start_turn() with no session_id creates CTO with a valid UUID session_id
  - Two calls without session_id produce different session_ids

InMemoryPersistencePurpose
  - events list contains hub_event_record dicts
  - Idempotent on event_id (duplicate write is silently dropped)
  - is_durable is False
"""

from __future__ import annotations

import warnings
from uuid import UUID, uuid4

import pytest
from conftest import RecordingPurpose

from turnturnturn import TTT, InMemoryPersistencePurpose, PersistenceFailureError
from turnturnturn.errors import UnauthorizedDispatchError
from turnturnturn.events import HubEvent, HubEventType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class DurablePersistencePurpose(InMemoryPersistencePurpose):
    """Test double that claims to be durable — used to verify no UserWarning."""

    @property
    def is_durable(self) -> bool:
        """Claim durability for tests that need to suppress the warning."""
        return True


# ---------------------------------------------------------------------------
# TTT.start() — persistence_purpose contract
# ---------------------------------------------------------------------------


def test_start_requires_persistence_purpose():
    with pytest.raises(TypeError):
        TTT.start()  # type: ignore[call-arg]


def test_start_rejects_non_protocol_object():
    with pytest.raises(TypeError):
        TTT.start("not a purpose")  # type: ignore[arg-type]


def test_start_emits_user_warning_for_non_durable(persistence_purpose):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        TTT.start(persistence_purpose)
    user_warnings = [w for w in caught if issubclass(w.category, UserWarning)]
    assert len(user_warnings) == 1
    assert "is_durable=False" in str(user_warnings[0].message)


def test_start_no_warning_for_durable():
    p = DurablePersistencePurpose()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        TTT.start(p)
    user_warnings = [w for w in caught if issubclass(w.category, UserWarning)]
    assert len(user_warnings) == 0


# ---------------------------------------------------------------------------
# session_started event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_started_is_first_event_in_persistence_log(
    hub, persistence_purpose
):
    # hub fixture constructs TTT.start(persistence_purpose). The
    # session_started write is scheduled via ensure_future during start(),
    # so we need one await to let the event loop flush it.
    await hub.start_purpose(RecordingPurpose())
    assert len(persistence_purpose.events) >= 1
    assert persistence_purpose.events[0]["event_type"] == "session_started"


@pytest.mark.asyncio
async def test_session_started_payload_fields(hub, persistence_purpose):
    await hub.start_purpose(RecordingPurpose())
    record = persistence_purpose.events[0]
    assert record["event_type"] == "session_started"
    payload = record["payload"]
    assert "hub_id" in payload
    assert "ttt_version" in payload
    assert "persister_name" in payload
    assert "persister_id" in payload
    assert "persister_is_durable" in payload
    assert "strict_profiles" in payload
    assert payload["persister_name"] == persistence_purpose.name
    assert payload["persister_id"] == str(persistence_purpose.id)
    assert payload["persister_is_durable"] is False
    UUID(payload["hub_id"])  # must be a valid UUID string


@pytest.mark.asyncio
async def test_session_started_not_delivered_to_domain_purposes(hub):
    p = RecordingPurpose()
    await hub.start_purpose(p)
    # p only sees purpose_started (its own registration event), not session_started
    event_types = [e.event_type for e in p.received]
    assert HubEventType.SESSION_STARTED not in event_types


# ---------------------------------------------------------------------------
# purpose_started event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_purpose_persists_purpose_started(hub, persistence_purpose):
    p = RecordingPurpose()
    await hub.start_purpose(p)
    # Flush session_started first, then purpose_started should follow
    event_types = [e["event_type"] for e in persistence_purpose.events]
    assert "purpose_started" in event_types


@pytest.mark.asyncio
async def test_purpose_started_payload_fields(hub, persistence_purpose):
    p = RecordingPurpose()
    await hub.start_purpose(p)
    record = next(
        e for e in persistence_purpose.events if e["event_type"] == "purpose_started"
    )
    payload = record["payload"]
    assert payload["purpose_name"] == p.name
    assert payload["purpose_id"] == str(p.id)
    assert payload["is_persistence_purpose"] is False


# ---------------------------------------------------------------------------
# Persistence-first routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_event_called_before_domain_purpose(
    persistence_purpose, session_id, minimal_content
):
    """
    Verify ordering: write_event must complete before take_turn reaches
    the domain Purpose. We instrument write_event to record a marker,
    then assert domain Purpose sees events only after persistence.
    """
    call_order: list[str] = []

    original_write = persistence_purpose.write_event

    async def instrumented_write(event: HubEvent) -> None:
        call_order.append("persist")
        await original_write(event)

    persistence_purpose.write_event = instrumented_write  # type: ignore[method-assign]

    domain = RecordingPurpose()

    original_take_turn = domain.take_turn

    async def instrumented_take_turn(event: HubEvent) -> None:
        call_order.append("domain")
        await original_take_turn(event)

    domain.take_turn = instrumented_take_turn  # type: ignore[method-assign]

    hub = TTT.start(persistence_purpose)
    await hub.start_purpose(domain)

    submitter = RecordingPurpose()
    submitter.name = "submitter"
    await hub.start_purpose(submitter)

    await hub.start_turn(
        "conversation",
        minimal_content,
        submitter.token,
        session_id=session_id,
    )

    # Every persist must come before its paired domain delivery
    for i, marker in enumerate(call_order):
        if marker == "domain":
            assert call_order[i - 1] == "persist", (
                f"domain delivery at position {i} was not preceded by persist: "
                f"{call_order}"
            )


@pytest.mark.asyncio
async def test_persistence_failure_raises_and_halts_delivery(
    persistence_purpose, session_id, minimal_content
):
    """Build a working hub, then inject a failing write_event for the turn call."""
    hub = TTT.start(persistence_purpose)

    domain = RecordingPurpose()
    await hub.start_purpose(domain)

    submitter = RecordingPurpose()
    submitter.name = "submitter"
    await hub.start_purpose(submitter)
    domain.received.clear()

    # Inject failure only for subsequent write_event calls
    async def failing_write(event):
        raise OSError("disk full")

    persistence_purpose.write_event = failing_write  # type: ignore[method-assign]

    with pytest.raises(PersistenceFailureError):
        await hub.start_turn(
            "conversation",
            minimal_content,
            submitter.token,
            session_id=session_id,
        )

    cto_events = [
        e for e in domain.received if e.event_type == HubEventType.CTO_STARTED
    ]
    assert len(cto_events) == 0


@pytest.mark.asyncio
async def test_persistence_failure_error_carries_context(
    persistence_purpose, session_id, minimal_content
):
    """Build a working hub, then inject a failing write_event for the turn call."""
    hub = TTT.start(persistence_purpose)

    submitter = RecordingPurpose()
    submitter.name = "submitter"
    await hub.start_purpose(submitter)

    async def failing_write(event):
        raise OSError("disk full")

    persistence_purpose.write_event = failing_write  # type: ignore[method-assign]

    with pytest.raises(PersistenceFailureError) as exc_info:
        await hub.start_turn(
            "conversation",
            minimal_content,
            submitter.token,
            session_id=session_id,
        )

    err = exc_info.value
    assert err.persister_name == persistence_purpose.name
    assert err.event_id is not None


# ---------------------------------------------------------------------------
# hub_token required for start_turn()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_turn_rejects_invalid_token(hub, session_id, minimal_content):
    with pytest.raises(UnauthorizedDispatchError):
        await hub.start_turn(
            "conversation",
            minimal_content,
            "not_a_real_token",
            session_id=session_id,
        )


@pytest.mark.asyncio
async def test_start_turn_no_started_on_auth_failure(hub, session_id, minimal_content):
    with pytest.raises(UnauthorizedDispatchError):
        await hub.start_turn(
            "conversation",
            minimal_content,
            "bad_token",
            session_id=session_id,
        )
    # No CTO should exist for this session
    assert hub.librarian.get_cto(session_id) is None


@pytest.mark.asyncio
async def test_start_turn_valid_token_starts_cto(
    hub, session_id, minimal_content, submitter
):
    turn_id = await hub.start_turn(
        "conversation",
        minimal_content,
        submitter.token,
        session_id=session_id,
    )
    assert hub.librarian.get_cto(turn_id) is not None


# ---------------------------------------------------------------------------
# hub-minted session_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_turn_mints_session_id_when_absent(hub, minimal_content, submitter):
    turn_id = await hub.start_turn(
        "conversation",
        minimal_content,
        submitter.token,
    )
    cto = hub.librarian.get_cto(turn_id)
    assert cto is not None
    assert isinstance(cto.session_id, UUID)


@pytest.mark.asyncio
async def test_start_turn_minted_session_ids_are_unique(
    hub, minimal_content, submitter
):
    t1 = await hub.start_turn("conversation", minimal_content, submitter.token)
    t2 = await hub.start_turn("conversation", minimal_content, submitter.token)
    sid1 = hub.librarian.get_cto(t1).session_id
    sid2 = hub.librarian.get_cto(t2).session_id
    assert sid1 != sid2


# ---------------------------------------------------------------------------
# InMemoryPersistencePurpose
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_in_memory_events_are_hub_event_records(
    hub, persistence_purpose, submitter, session_id, minimal_content
):
    await hub.start_turn(
        "conversation",
        minimal_content,
        submitter.token,
        session_id=session_id,
    )
    cto_record = next(
        e for e in persistence_purpose.events if e["event_type"] == "cto_started"
    )
    assert "event_id" in cto_record
    assert "event_type" in cto_record
    assert "payload" in cto_record
    UUID(cto_record["event_id"])  # must be valid UUID string


@pytest.mark.asyncio
async def test_in_memory_write_event_idempotent_on_event_id(persistence_purpose):
    """Duplicate delivery of the same event_id must not double-append."""
    hub = TTT.start(persistence_purpose)
    await hub.start_purpose(RecordingPurpose())  # flush session_started

    count_before = len(persistence_purpose.events)

    # Construct a synthetic event and write it twice
    from turnturnturn.events import EmptyPayload

    event = HubEvent(
        event_type=HubEventType.CTO_STARTED,
        event_id=uuid4(),
        created_at_ms=0,
        payload=EmptyPayload(),
    )
    await persistence_purpose.write_event(event)
    await persistence_purpose.write_event(event)  # duplicate

    assert len(persistence_purpose.events) == count_before + 1


def test_in_memory_is_durable_is_false():
    p = InMemoryPersistencePurpose()
    assert p.is_durable is False
