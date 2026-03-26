"""Shared fixtures and configuration for the TTT test suite."""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio

from turnturnturn import (
    TTT,
    BasePurpose,
    InMemoryPersistencePurpose,
    SessionOwnerPurpose,
)
from turnturnturn.events import HubEvent

pytest_plugins = ("pytest_asyncio",)


class RecordingPurpose(BasePurpose):
    """A BasePurpose subclass that records every event it receives."""

    name = "recording"

    def __init__(self) -> None:
        super().__init__()
        self.id = uuid4()
        self.received: list[HubEvent] = []

    async def _handle_event(self, event: HubEvent) -> None:
        self.received.append(event)


class NamedPurpose(BasePurpose):
    """A BasePurpose subclass with a configurable name."""

    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name
        self.id = uuid4()
        self.received: list[HubEvent] = []

    async def _handle_event(self, event: HubEvent) -> None:
        self.received.append(event)


class RecordingSessionOwnerPurpose(SessionOwnerPurpose):
    """A SessionOwnerPurpose test double that records every event it receives."""

    name = "session_owner"

    def __init__(self) -> None:
        super().__init__()
        self.id = uuid4()
        self.received: list[HubEvent] = []

    async def _handle_event(self, event: HubEvent) -> None:
        self.received.append(event)


@pytest.fixture
def persistence_purpose() -> InMemoryPersistencePurpose:
    """A fresh InMemoryPersistencePurpose for each test."""
    return InMemoryPersistencePurpose()


@pytest.fixture
def session_owner() -> RecordingSessionOwnerPurpose:
    """A fresh startup session owner for each test."""
    return RecordingSessionOwnerPurpose()


@pytest.fixture
def hub(
    persistence_purpose: InMemoryPersistencePurpose,
    session_owner: RecordingSessionOwnerPurpose,
) -> TTT:
    """A TTT hub backed by an InMemoryPersistencePurpose."""
    return TTT.start(persistence_purpose, session_owner_purpose=session_owner)


@pytest_asyncio.fixture
async def submitter(
    hub: TTT,
    session_owner: RecordingSessionOwnerPurpose,
) -> RecordingSessionOwnerPurpose:
    """
    A registered RecordingPurpose whose token is used to call start_turn().

    Tests that need to call hub.start_turn() should use this fixture to
    supply hub_token. Tests that need to verify token rejection should
    construct events directly.
    """
    return session_owner


@pytest.fixture
def session_id():
    """A stable session UUID for the duration of a test."""
    return uuid4()


@pytest.fixture
def minimal_content() -> dict:
    """Minimal valid conversation profile content."""
    return {"speaker": {"id": "usr_test"}, "text": "hello"}


@pytest.fixture
def full_content() -> dict:
    """Fully populated conversation profile content with all optional fields."""
    return {
        "speaker": {"id": "usr_test", "role": "user", "label": "Tester"},
        "text": "hello",
    }
