"""Structural protocols for TTT participants: TurnTakerProtocol and PurposeProtocol."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable
from uuid import UUID

if TYPE_CHECKING:
    from .events import HubEvent


@runtime_checkable
class TurnTakerProtocol(Protocol):
    """
    A component that can receive HubEvents and optionally emit Deltas.

    NOTE:
    - "TurnTaker" is a capability role (can participate in the event mesh).
    - "Purpose" is the agenda-bearing registered actor (see PurposeProtocol).
    """

    async def take_turn(self, event: HubEvent) -> None: ...


@runtime_checkable
class PurposeProtocol(TurnTakerProtocol, Protocol):
    """
    A registered agenda-bearing actor in the TTT mesh.

    Identification:
      - name: semantic kind ("ca", "embeddingizer", "socratic", ...)
      - id: per-instance UUID (multiple instances can share the same name)
      - token: hub-assigned token, None until registered with a hub.

    BasePurpose is the recommended implementation base — it enforces that
    take_turn() rejects events whose hub_token does not match the assigned
    token, closing the point-to-point bypass. Raw PurposeProtocol
    implementors (e.g. test doubles) receive hub_token=None and bypass
    validation. ttt.start_purpose() accepts either.

    The hub uses (id, token) for per-recipient dispatch. Purposes are
    registered via ttt.start_purpose(), which assigns the token.
    """

    name: str
    id: UUID
    token: str | None
