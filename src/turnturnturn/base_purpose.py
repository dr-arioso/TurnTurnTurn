"""
BasePurpose — abstract base class for all TTT Purposes.

Consuming projects subclass BasePurpose and implement _handle_event().
The public dispatch entry point (take_turn()) is owned by this base class
and must not be overridden — it validates hub-issued routing credentials
before delegating to _handle_event().

The hub assigns two route credentials at registration time via
ttt.start_purpose():

- token: authenticates Purpose -> hub communication
- downlink_signature: verifies hub -> Purpose downlink routing

Until registered, the Purpose is unbound and take_turn() raises
UnboundPurposeError. After registration, only HubEvents carrying both the
matching hub_token and matching downlink_signature are accepted.

This design closes the point-to-point bypass: because take_turn() validates
hub-issued route credentials, a Purpose cannot receive hub-looking events
from any source other than the hub that registered it.

Subclass contract:
  - Implement _handle_event(event) for domain logic.
  - Do not override take_turn().
  - Pass name and id to super().__init__() or set them as class attributes.
  - Do not set _token or _downlink_signature directly — both are assigned
    exclusively by the hub.
"""

from __future__ import annotations

import abc
from uuid import UUID

from .errors import (
    InvalidDownlinkSignatureError,
    UnauthorizedDispatchError,
    UnboundPurposeError,
)
from .events import HubEvent

_UNBOUND = object()


class BasePurpose(abc.ABC):
    """
    Abstract base class for TTT Purposes.

    Implements the TurnTakerProtocol / PurposeProtocol contract with
    hub-issued route validation built in. Subclasses implement
    _handle_event() for domain logic and must not override take_turn().
    """

    name: str
    id: UUID

    def __init__(self) -> None:
        """Initialise the base Purpose in unbound state."""
        self._token: object = _UNBOUND
        self._downlink_signature: object = _UNBOUND

    @property
    def token(self) -> str | None:
        """
        The hub-assigned token for this Purpose instance.

        None until registered with a hub. After registration, always a
        non-empty string. Never set this directly — use ttt.start_purpose().
        """
        if self._token is _UNBOUND:
            return None
        return self._token  # type: ignore[return-value]

    @property
    def downlink_signature(self) -> str | None:
        """
        The hub-issued downlink signature for this Purpose instance.

        None until registered with a hub. After registration, always a
        non-empty string for BasePurpose subclasses.
        """
        if self._downlink_signature is _UNBOUND:
            return None
        return self._downlink_signature  # type: ignore[return-value]

    def _assign_token(self, token: str) -> None:
        """
        Assign the Purpose's token. Called exclusively by ttt.start_purpose().
        """
        if not token:
            raise ValueError("hub token must be a non-empty string")
        self._token = token

    def _assign_downlink_signature(self, downlink_signature: str) -> None:
        """
        Assign the hub-issued downlink signature.

        Called exclusively by ttt.start_purpose().
        """
        if not downlink_signature:
            raise ValueError("downlink signature must be a non-empty string")
        self._downlink_signature = downlink_signature

    async def take_turn(self, event: HubEvent) -> None:
        """
        Validate the hub token and downlink signature, then delegate to _handle_event().

        This is the hub-facing downlink entry point. It must not be overridden
        by subclasses — override _handle_event() instead.

        Validates that:
          1. This Purpose has been registered with a hub.
          2. The event carries a token matching this Purpose's token.
          3. The event carries a downlink_signature matching this Purpose's
             assigned signature.
        """
        if self._token is _UNBOUND or self._downlink_signature is _UNBOUND:
            raise UnboundPurposeError(
                f"Purpose {self.name!r} (id={self.id}) has not been registered "
                f"with a hub. Call ttt.start_purpose() before dispatch."
            )

        if event.hub_token != self._token:
            raise UnauthorizedDispatchError(
                f"Purpose {self.name!r} (id={self.id}) rejected event "
                f"{event.event_id} — hub token mismatch."
            )

        if event.downlink_signature != self._downlink_signature:
            raise InvalidDownlinkSignatureError(
                f"Purpose {self.name!r} (id={self.id}) rejected event "
                f"{event.event_id} — downlink signature mismatch."
            )

        await self._handle_event(event)

    @abc.abstractmethod
    async def _handle_event(self, event: HubEvent) -> None:
        """
        Handle a validated HubEvent. Implement domain logic here.

        Called by take_turn() after hub-issued routing validation passes.
        """
