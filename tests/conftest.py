"""Shared fixtures and configuration for the TTT test suite."""

from __future__ import annotations

from uuid import uuid4

import pytest

from turnturnturn import TTT, BasePurpose
from turnturnturn.events import HubEvent

# ---------------------------------------------------------------------------
# pytest-asyncio mode
# ---------------------------------------------------------------------------

pytest_plugins = ("pytest_asyncio",)


# ---------------------------------------------------------------------------
# Minimal concrete Purpose implementations for tests
# ---------------------------------------------------------------------------


class RecordingPurpose(BasePurpose):
    """A BasePurpose subclass that records every event it receives.

    Used throughout the test suite to assert dispatch behaviour without
    requiring any domain logic.
    """

    name = "recording"

    def __init__(self) -> None:
        super().__init__()
        self.id = uuid4()
        self.received: list[HubEvent] = []

    async def _handle_event(self, event: HubEvent) -> None:
        """Record the event."""
        self.received.append(event)


class NamedPurpose(BasePurpose):
    """A BasePurpose subclass with a configurable name.

    Allows tests to register multiple Purposes with distinct names
    (and therefore distinct observation namespaces) without defining a
    new class per test.
    """

    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name
        self.id = uuid4()
        self.received: list[HubEvent] = []

    async def _handle_event(self, event: HubEvent) -> None:
        """Record the event."""
        self.received.append(event)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def hub() -> TTT:
    """Return a fresh TTT hub with default profiles loaded."""
    return TTT.create()


@pytest.fixture
def session_id():
    """Return a stable session UUID for a single test."""
    return uuid4()


@pytest.fixture
def minimal_content() -> dict:
    """Minimal valid conversation content (no optional fields)."""
    return {"speaker": {"id": "usr_test"}, "text": "hello"}


@pytest.fixture
def full_content() -> dict:
    """Conversation content with all optional fields supplied."""
    return {
        "speaker": {"id": "usr_test", "role": "user", "label": "Tester"},
        "text": "hello",
    }
