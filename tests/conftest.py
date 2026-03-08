"""Shared fixtures and configuration for the TTT test suite."""

from __future__ import annotations

from uuid import uuid4

import pytest

from turnturnturn import TTT, BasePurpose
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


@pytest.fixture
def hub() -> TTT:
    return TTT.start()


@pytest.fixture
def session_id():
    return uuid4()


@pytest.fixture
def minimal_content() -> dict:
    return {"speaker": {"id": "usr_test"}, "text": "hello"}


@pytest.fixture
def full_content() -> dict:
    return {
        "speaker": {"id": "usr_test", "role": "user", "label": "Tester"},
        "text": "hello",
    }
