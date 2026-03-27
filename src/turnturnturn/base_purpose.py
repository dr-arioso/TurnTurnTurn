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
import time
from typing import TYPE_CHECKING
from uuid import UUID

from .errors import (
    InvalidDownlinkSignatureError,
    UnauthorizedDispatchError,
    UnboundPurposeError,
)
from .events import (
    CTORequestEvent,
    CTORequestPayload,
    EndSessionEvent,
    EndSessionPayload,
    HubEvent,
    HubEventType,
    PurposeCompletedEvent,
    PurposeCompletedPayload,
    PurposeStartedEvent,
    PurposeStartedPayload,
)
from .protocols import PurposeEventProtocol

if TYPE_CHECKING:
    from .hub import TTT

_UNBOUND = object()


class BasePurpose(abc.ABC):
    """
    Abstract base class for TTT Purposes.

    Implements the TurnTakerProtocol / PurposeProtocol contract with
    hub-issued route validation built in. Subclasses implement
    _handle_event() for domain logic and must not override take_turn().

    Architectural role:
      - A Purpose is the mesh-visible actor; ambient calling code is not.
      - Registered Purposes may emit mesh events back through the hub.
      - The base class provides common lifecycle affordances such as
        `end_session()` and default `session_closing` acknowledgement so
        domain packages do not need to re-implement that substrate logic.

    Intended lifecycle direction:
      - startup and shutdown provenance belong to the mesh lifecycle model
      - ordinary Purposes should only need the generic contracts exposed here
      - packages such as Adjacency should not own TTT bootstrap policy
    """

    name: str
    id: UUID

    def __init__(self) -> None:
        """Initialise the base Purpose in unbound state."""
        self._token: object = _UNBOUND
        self._downlink_signature: object = _UNBOUND
        self._hub: TTT | object = _UNBOUND
        self._acknowledged_session_closing: set[str] = set()
        self._announced_started = False
        self._requested_session_end: set[str] = set()

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

    def _assign_hub(self, hub: TTT) -> None:
        """Bind this Purpose instance to the hub that registered it."""
        self._hub = hub

    def _require_token(self) -> str:
        """Return the bound hub token or raise until registration is complete."""
        token = self.token
        if token is None:
            raise UnboundPurposeError(
                f"Purpose {self.name!r} (id={self.id}) has not been registered "
                f"with a hub. Call ttt.start_purpose() before dispatch."
            )
        return token

    @property
    def hub(self) -> TTT:
        """Return the bound hub. Raises until the Purpose is registered."""
        if self._hub is _UNBOUND:
            raise UnboundPurposeError(
                f"Purpose {self.name!r} (id={self.id}) has not been registered "
                f"with a hub. Call ttt.start_purpose() before dispatch."
            )
        return self._hub  # type: ignore[return-value]

    async def end_session(self, session_id: str, *, reason: str = "normal") -> None:
        """
        Request hub-managed shutdown for a session visible to this Purpose.

        This helper exists so lifecycle-capable Purposes do not need to
        hand-assemble the `EndSessionEvent` envelope repeatedly. Whether the
        request succeeds is still governed by hub-side policy, including
        session-owner checks.
        """
        if not session_id:
            raise ValueError("session_id must be a non-empty string")
        if session_id in self._requested_session_end:
            return
        self._requested_session_end.add(session_id)
        await self._submit_purpose_event(
            EndSessionEvent(
                purpose_id=self.id,
                purpose_name=self.name,
                hub_token=self._require_token(),
                payload=EndSessionPayload(session_id=session_id, reason=reason),
            )
        )

    async def request_cto(
        self,
        *,
        session_id: str,
        source_kind: str,
        source_locator: str,
        session_code: str | None = None,
        request_id: str | None = None,
    ) -> None:
        """
        Request that the persistence layer import a CTO document into the mesh.

        This is the mesh-native sibling to `start_turn()`: the caller does not
        hand the hub turn content directly, but instead asks persistence to
        retrieve and reconstitute a CTO-shaped document from an external source.
        """
        if not session_id:
            raise ValueError("session_id must be a non-empty string")
        if not source_kind:
            raise ValueError("source_kind must be a non-empty string")
        if not source_locator:
            raise ValueError("source_locator must be a non-empty string")
        session_uuid = UUID(session_id)
        await self._submit_purpose_event(
            CTORequestEvent(
                purpose_id=self.id,
                purpose_name=self.name,
                hub_token=self._require_token(),
                session_id=session_uuid,
                payload=CTORequestPayload(
                    session_id=session_id,
                    source_kind=source_kind,
                    source_locator=source_locator,
                    requested_by_purpose_id=str(self.id),
                    requested_by_purpose_name=self.name,
                    session_code=session_code,
                    request_id=request_id,
                ),
            )
        )

    async def announce_started(self, *, is_persistence_purpose: bool = False) -> None:
        """
        Emit purpose_started provenance once this Purpose has joined the mesh.

        Registration is still immediate. This event is informational and
        provenance-oriented rather than a second handshake required to
        complete admission.
        """
        if self._announced_started:
            return
        self._announced_started = True
        await self._submit_purpose_event(
            PurposeStartedEvent(
                purpose_id=self.id,
                purpose_name=self.name,
                hub_token=self._require_token(),
                payload=PurposeStartedPayload(
                    purpose_name=self.name,
                    purpose_id=str(self.id),
                    is_persistence_purpose=is_persistence_purpose,
                    created_at_ms=int(time.time() * 1000),
                ),
            )
        )

    async def complete_session_closing(
        self,
        session_id: str,
        *,
        reason: str = "normal",
    ) -> None:
        """
        Acknowledge that this Purpose has finished its shutdown work.

        The default `session_closing` path in BasePurpose calls this
        immediately. Purposes with real evacuation work may override
        `_on_session_closing()` and call this helper only after local cleanup
        is complete.
        """
        if not session_id:
            raise ValueError("session_id must be a non-empty string")
        if session_id in self._acknowledged_session_closing:
            return
        self._acknowledged_session_closing.add(session_id)
        await self._submit_purpose_event(
            PurposeCompletedEvent(
                purpose_id=self.id,
                purpose_name=self.name,
                hub_token=self._require_token(),
                payload=PurposeCompletedPayload(session_id=session_id, reason=reason),
            )
        )

    async def _submit_purpose_event(self, event: PurposeEventProtocol) -> UUID | None:
        """
        Submit a Purpose-authored event through the hub.

        Ordinary Purposes only route the event to the hub. Persistence
        Purposes override this hook so their self-authored events are written
        by the persistence layer as part of emission rather than routed back
        into persistence by the hub.
        """
        return await self.hub.take_turn(event)

    async def _on_session_closing(self, event: HubEvent) -> None:
        """
        Default shutdown handling: immediately acknowledge closing.

        Override this in subclasses that need to flush state or finish
        bounded work before they report `purpose_completed`.
        """
        if event.session_id is None:
            return
        await self.complete_session_closing(str(event.session_id))

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

        `session_closing` is intercepted here and routed through
        `_on_session_closing()` so the default lifecycle behavior lives in the
        substrate rather than being recopied in downstream packages.
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

        if event.event_type == HubEventType.SESSION_CLOSING:
            await self._on_session_closing(event)
            return

        await self._handle_event(event)

    @abc.abstractmethod
    async def _handle_event(self, event: HubEvent) -> None:
        """
        Handle a validated HubEvent. Implement domain logic here.

        Called by take_turn() after hub-issued routing validation passes.
        """


class SessionOwnerPurpose(BasePurpose):
    """
    Marker base class for the explicit startup-time session owner.

    A TTT hub boots with a required session-owner Purpose alongside the
    persistence Purpose. The owner is the only Purpose permitted to create the
    first turn for a new session; after that, normal per-session ownership
    rules continue to govern owner-only actions such as `end_session`.

    This class is intentionally lightweight. It makes startup authority
    explicit without forcing a single domain-independent `start_session()` API
    on all consuming packages.
    """
