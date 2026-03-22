"""
TTT hub runtime — authoritative CTO creation, Delta merge, and event emission.

Internal observability uses the standard library logger ``turnturnturn.hub``.
Configure it in the consuming application; no handlers are attached here.
Key events logged: purpose registration (DEBUG), CTO creation (DEBUG),
delta merge (DEBUG), auth failures (WARNING), merge errors (WARNING).

# TODO(future-pr): TTT.start() uses a synchronous shim (asyncio.get_event_loop /
# run_until_complete) to write the session_started bootstrap event because start()
# is a classmethod with no event loop. The clean fix is to make TTT.start() async
# or to accept a pre-built event loop. Deferred until the bootstrap ergonomics are
# revisited holistically.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import importlib.metadata
import logging
import secrets
import time
import warnings
from dataclasses import dataclass, field
from typing import Any, cast
from uuid import UUID, uuid4

from turnturnturn.errors import UnauthorizedDispatchError

from .base_purpose import BasePurpose
from .cto import CTO
from .delta import Delta
from .errors import PersistenceFailureError, UnknownEventTypeError
from .events import (
    CTOStartedPayload,
    DeltaMergedPayload,
    DeltaRejectedPayload,
    HubEvent,
    HubEventType,
    PurposeEventType,
    PurposeStartedPayload,
    SessionClosingPayload,
    SessionCompletedPayload,
    SessionStartedPayload,
)
from .events.hub_events import DeltaProposalPayload
from .profile import ProfileRegistry
from .protocols import (
    CTOPersistencePurposeProtocol,
    EventPayloadProtocol,
    PurposeEventProtocol,
    PurposeProtocol,
)
from .registry import PurposeRegistration

# ---------------------------------------------------------------------------
# Hub event policy
#
# Determines which Purpose-authored events trigger built-in hub action.
# All events still pass through the hub substrate path regardless of whether
# a built-in handler is registered.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _EventPolicy:
    handler: str | None = None


_EVENT_POLICY: dict[PurposeEventType, _EventPolicy] = {
    PurposeEventType.DELTA_PROPOSAL: _EventPolicy(handler="_handle_delta_proposal"),
    PurposeEventType.PURPOSE_COMPLETED: _EventPolicy(handler=None),
    # CTOCloseRequest is accepted but not yet acted upon. The DAG layer will
    # implement quiescence detection and CTO_COMPLETED emission.
    PurposeEventType.CTO_CLOSE_REQUEST: _EventPolicy(handler=None),
}

# Custom event type registry (populated by TTT.register_event_type()).
# Maps event_type string → multicast flag.
_CUSTOM_EVENT_POLICY: dict[str, bool] = {}


"""
CTO creation boundary:
start_turn(content_profile, content, hub_token, ...)
    -> look up Profile from ProfileRegistry
    -> validate content against profile contract
    -> apply profile defaults (profile reads/writes opaque session context)
    -> create CTO with content_profile = {"id": ..., "version": ...}
    -> emit cto_started
    -> dispatch to registered Purposes
"""


def now_ms() -> int:
    """Return current Unix time in milliseconds. Used for CTO and event timestamps."""
    return int(time.time() * 1000)


_logger = logging.getLogger("turnturnturn.hub")
# Configure via standard logging — e.g. logging.getLogger("turnturnturn.hub").setLevel(logging.DEBUG)
# No handlers are attached here; the consuming application owns handler configuration.


@dataclass
class Librarian:
    """
    Read interface for canonical CTO state.

    ttt.librarian is the query path for Purposes that need full CTO content
    or observations. HubEvent payloads carry only a CTOIndex (lightweight
    routing reference); Purposes call librarian.get_cto() when they need
    more. ctoPersistPurpose is the canonical consumer of this pattern.

    The hub is the authority and router; the librarian is the read path.
    Its responsibilities will grow: point lookups today, session readback
    and replay queries later (likely against a persistence layer).
    """

    _ctos: dict[UUID, CTO]

    def get_cto(self, turn_id: UUID) -> CTO | None:
        """
        Return the current canonical CTO for turn_id, or None if unknown.

        The returned CTO reflects the hub's canonical state at the moment of
        the call — for delta_merged events, this is the post-merge state.
        Do not cache the result across event boundaries; the hub is the sole
        writer and may replace the CTO instance on any merge.

        Args:
            turn_id: The turn_id of the CTO to retrieve.

        Returns:
            The canonical CTO, or None if turn_id is not known to this hub.
        """
        return self._ctos.get(turn_id)


@dataclass
class TTT:
    """
    TurnTurnTurn hub runtime.

    The hub is the sole authority for CTO creation, Delta merge, and event
    emission. All content ingress goes through start_turn(); nothing
    constructs CTOs directly.

    Instantiate via TTT.start() — do not construct directly. TTT.start()
    ensures built-in profiles are registered before the hub is used.

    Profile lookup delegates to the process-scoped ProfileRegistry class.
    Profiles are registered directly on ProfileRegistry at process startup —
    not through the hub.

    The hub maintains an opaque per-session context dict for each active
    session and passes it to Profile.apply_defaults() as a mutable dict.
    The hub never inspects context contents — profiles own them entirely.
    This allows profiles to maintain session-scoped state (e.g. speaker
    ordinals for label defaults) without leaking domain knowledge into the hub.

    Attributes:
        registrations: Registry of all non-persistence Purposes, keyed by
            purpose.id. Consulted for multicast delivery and take_turn()
            validation.
        strict_profiles: When True, unknown content keys are rejected at
            start_turn() time for all profiles.
        hub_id: Unique identifier for this hub instance. Recorded in the
            session_started event for audit and replay provenance.
        librarian: The read interface for canonical CTO state. Purposes
            call ttt.librarian.get_cto(turn_id) when they need full CTO
            content or observations beyond what CTOIndex carries.
    """

    registrations: dict[UUID, PurposeRegistration]
    strict_profiles: bool = False
    hub_id: UUID = field(default_factory=uuid4)
    persistence_purpose: CTOPersistencePurposeProtocol | None = field(
        default=None, repr=False
    )
    _session_contexts: dict[UUID, dict[str, Any]] = field(
        default_factory=dict, init=False, repr=False
    )
    # Canonical CTO store: turn_id → CTO.
    # The hub is the sole writer. CTOs are replaced (not mutated) on Delta merge
    # because CTO is frozen — a new instance is constructed with updated observations.
    _ctos: dict[UUID, CTO] = field(default_factory=dict, init=False, repr=False)
    _hub_secret: str = field(default_factory=lambda: secrets.token_hex(32), repr=False)
    _bootstrap_persist_task: asyncio.Task[None] | None = field(
        default=None, init=False, repr=False
    )
    librarian: Librarian = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Wire the librarian to the hub's CTO store after dataclass init."""
        self.librarian = Librarian(_ctos=self._ctos)

    @classmethod
    def start(
        cls,
        persistence_purpose: CTOPersistencePurposeProtocol,
        *,
        strict_profiles: bool = False,
    ) -> "TTT":
        """
        Start a new TTT hub and ensure built-in profiles are loaded.

        persistence_purpose is a required positional argument. The hub will
        not start without a registered persistence backend. This enforces the
        architectural invariant that every event reaches a durable sink before
        any other routing.

        Emits session_started directly to the persistence Purpose as its
        first act — before any other registration or dispatch. This event
        is the first record in the event log and carries hub provenance
        (hub_id, ttt_version, persister identity, is_durable).

        A UserWarning is issued if persistence_purpose.is_durable is False.
        Non-durable backends (e.g. InMemoryPersistencePurpose) are valid
        for development but should not be used in production.

        Calls ProfileRegistry.load_defaults() to register built-in profiles
        if not already present. Safe to call multiple times in the same process.

        Args:
            persistence_purpose: A CTOPersistencePurposeProtocol implementor.
                Must be provided; there is no default.
            strict_profiles: If True, enforce strict key validation on all
                profiles at start_turn() time.

        Returns:
            A new TTT hub instance ready to accept Purposes and turns.

        Raises:
            TypeError: If persistence_purpose does not satisfy
                CTOPersistencePurposeProtocol.
        """
        if not isinstance(persistence_purpose, CTOPersistencePurposeProtocol):
            raise TypeError(
                "TTT.start() requires a CTOPersistencePurposeProtocol instance; "
                f"got {type(persistence_purpose)!r}. "
                "Pass an InMemoryPersistencePurpose for development."
            )

        if not persistence_purpose.is_durable:
            warnings.warn(
                f"Persistence backend {persistence_purpose.name!r} has "
                "is_durable=False. Events will not survive process restart. "
                "Use a durable backend in production.",
                UserWarning,
                stacklevel=2,
            )

        ProfileRegistry.load_defaults()

        hub = cls(
            registrations={},
            strict_profiles=strict_profiles,
            persistence_purpose=persistence_purpose,
        )
        # Bootstrap the persister: assign credentials, emit session_started.
        # This is synchronous because start() is a classmethod and no event
        # loop is available at this point. The persister's write_event() is
        # called via a synchronous shim for this one bootstrap event only.
        hub._bootstrap_persister()
        return hub

    @classmethod
    def register_event_type(cls, event_type: str, *, multicast: bool = True) -> None:
        """Register a custom Purpose-originated event type with the hub.

        Registered types are accepted by take_turn(). If multicast=True (default),
        the event is relayed as a HubEvent to all registered Purposes and the
        persistence backend. If multicast=False, the event is accepted and validated
        but silently dropped.

        Call before TTT.start() or before the first hub.start_turn() call.
        """
        normalized = event_type.replace("_", "").replace(".", "")
        if (
            not event_type
            or not normalized.isalnum()
            or event_type.startswith(".")
            or event_type.endswith(".")
        ):
            raise ValueError(
                f"event_type must be a non-empty alphanumeric/underscore/dotted-namespace string "
                f"(e.g. 'adjacency.stimulus'); got {event_type!r}"
            )
        _CUSTOM_EVENT_POLICY[event_type] = multicast

    def _bootstrap_persister(self) -> None:
        """
        Assign route credentials to the persistence Purpose and emit session_started.

        Called once by TTT.start() before any other registration or dispatch.
        The session_started event is written directly to the persister — it is
        never multicast and predates the event mesh.

        This method is synchronous because TTT.start() is a classmethod with
        no event loop. If a loop is already running, the bootstrap write is
        scheduled and later awaited by the first async hub operation so log
        ordering remains deterministic.
        """
        p = self.persistence_purpose
        assert p is not None  # invariant: called only from start()

        if isinstance(p, BasePurpose):
            token = secrets.token_hex(16)
            downlink_signature = self._build_downlink_signature(token, p.id)
            p._assign_token(token)
            p._assign_downlink_signature(downlink_signature)

        try:
            ttt_version = importlib.metadata.version("turnturnturn")
        except importlib.metadata.PackageNotFoundError:
            ttt_version = "unknown"

        event = HubEvent(
            event_type=HubEventType.SESSION_STARTED,
            event_id=uuid4(),
            created_at_ms=now_ms(),
            payload=SessionStartedPayload(
                hub_id=str(self.hub_id),
                ttt_version=ttt_version,
                persister_name=p.name,
                persister_id=str(p.id),
                persister_is_durable=p.is_durable,
                strict_profiles=self.strict_profiles,
                created_at_ms=now_ms(),
            ),
        )

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                self._bootstrap_persist_task = loop.create_task(p.write_event(event))
            else:
                loop.run_until_complete(p.write_event(event))
        except RuntimeError:
            asyncio.run(p.write_event(event))

    async def _await_bootstrap_persist(self) -> None:
        """
        Ensure the bootstrap session_started write has completed.

        This matters when TTT.start() is called inside an already-running event
        loop and _bootstrap_persister() had to schedule the write as a task.
        All later async hub operations await that task first so session_started
        remains the first persisted record.
        """
        task = self._bootstrap_persist_task
        if task is None:
            return

        self._bootstrap_persist_task = None

        try:
            await task
        except Exception as exc:
            p = self.persistence_purpose
            name = p.name if p is not None else "unknown"
            raise PersistenceFailureError(
                "Persistence write failed for bootstrap session_started event "
                f"(persister={name!r}): {exc}",
                persister_name=name,
                event_id=None,
            ) from exc

    def _session_context(self, session_id: UUID) -> dict[str, Any]:
        """
        Return the mutable context dict for session_id, creating it if absent.

        The returned dict is passed to Profile.apply_defaults() on each
        start_turn() call for this session. Its contents are entirely
        profile-owned — the hub neither reads nor writes them.
        """
        if session_id not in self._session_contexts:
            self._session_contexts[session_id] = {}
        return self._session_contexts[session_id]

    def _build_downlink_signature(self, token: str, purpose_id: UUID) -> str:
        """
        Derive a per-hub-instance, per-Purpose downlink signature.

        This is an anti-bypass / route-integrity check, not a claim of
        adversarial cryptographic security.
        """
        message = f"{token}:{purpose_id}".encode("utf-8")
        return hmac.new(
            self._hub_secret.encode("utf-8"),
            message,
            hashlib.sha256,
        ).hexdigest()

    def _resolve_registration_for_token(self, token: str) -> PurposeRegistration:
        """
        Resolve a registration from a hub-issued ingress token.

        Raises:
            UnauthorizedDispatchError: If the token does not resolve to
                exactly one current registration. Logged at WARNING before
                raising.
        """
        matches = [reg for reg in self.registrations.values() if reg.token == token]
        if len(matches) != 1:
            _logger.warning(
                "hub token not resolved: %d matching registrations (expected 1)",
                len(matches),
            )
            raise UnauthorizedDispatchError(
                "Purpose-originated event rejected — invalid hub token."
            )
        return matches[0]

    def _resolve_registration_for_token_all(self, token: str) -> PurposeRegistration:
        """
        Resolve a registration from a hub-issued token, searching both
        domain registrations and the persistence Purpose.

        Used by start_turn() to authenticate the submitting caller. Any
        registered Purpose — domain or persistence — may submit turns.

        Raises:
            UnauthorizedDispatchError: If the token does not resolve to
                exactly one registration across both stores.
        """
        # Check domain registrations first.
        matches = [reg for reg in self.registrations.values() if reg.token == token]

        # Also check the persistence Purpose — it may legitimately submit turns.
        p = self.persistence_purpose
        if p is not None and isinstance(p, BasePurpose) and p.token == token:
            matches.append(
                PurposeRegistration(
                    purpose=p,
                    token=p.token,
                    downlink_signature=p.downlink_signature,
                    subscriptions=[],
                )
            )

        if len(matches) != 1:
            _logger.warning(
                "start_turn token not resolved: %d matching registrations (expected 1)",
                len(matches),
            )
            raise UnauthorizedDispatchError(
                "start_turn() rejected — hub_token does not resolve to a "
                "registered Purpose."
            )
        return matches[0]

    async def start_purpose(
        self,
        purpose: PurposeProtocol,
        *,
        subscriptions: list[dict[str, Any]] | None = None,
    ) -> None:
        """
        Bootstrap a Purpose into the hub and assign its route credentials.

        start_purpose() stands outside the event model because no authenticated
        ingress event can exist until the Purpose has been registered.

        BasePurpose instances receive two hub-issued credentials:

        - token: authenticates Purpose -> hub communication
        - downlink_signature: verifies hub -> Purpose downlink routing

        Raw PurposeProtocol implementors may still be registered for tests, but
        they do not participate in BasePurpose route validation.

        Emits purpose_started via _multicast() after registration, so all
        previously registered Purposes (and the persistence backend) learn
        about each new participant.
        """
        await self._await_bootstrap_persist()

        token: str | None = None
        downlink_signature: str | None = None

        if isinstance(purpose, BasePurpose):
            token = secrets.token_hex(16)
            downlink_signature = self._build_downlink_signature(token, purpose.id)
            purpose._assign_token(token)
            purpose._assign_downlink_signature(downlink_signature)

        subs = subscriptions or []
        self.registrations[purpose.id] = PurposeRegistration(
            purpose=purpose,
            token=token,
            downlink_signature=downlink_signature,
            subscriptions=subs,
        )
        _logger.debug(
            "purpose registered: name=%r id=%s token_assigned=%s",
            purpose.name,
            purpose.id,
            token is not None,
        )

        is_persistence = isinstance(purpose, CTOPersistencePurposeProtocol)
        purpose_started_event = HubEvent(
            event_type=HubEventType.PURPOSE_STARTED,
            event_id=uuid4(),
            created_at_ms=now_ms(),
            payload=PurposeStartedPayload(
                purpose_name=purpose.name,
                purpose_id=str(purpose.id),
                is_persistence_purpose=is_persistence,
                created_at_ms=now_ms(),
            ),
        )
        await self._multicast(purpose_started_event)

    async def start_turn(
        self,
        content_profile: str,
        content: dict[str, Any],
        hub_token: str,
        *,
        session_id: UUID | None = None,
        profile_version: int = 1,
        request_id: str | None = None,
    ) -> UUID:
        """
        Look up the profile, validate content, apply defaults, create a CTO,
        emit cto_started, then dispatch to registered Purposes.

        start_turn() is a bootstrap method: it stands outside the event model
        because no CTOIndex exists until a CTO is started, so no well-formed
        event can represent this act.

        hub_token is required. The submitting caller must be a registered
        Purpose (domain or persistence). The hub validates the token and
        records the submitter's identity in the cto_started event payload.
        No CTO is started if authentication fails.

        session_id is optional. If not provided, the hub mints a new UUID.
        Callers that manage sessions explicitly should supply it; Purposes
        that generate new CTOs as part of processing may omit it.

        The hub is the sole authority for CTO creation. Callers may not
        construct CTOs directly. If the profile is unknown or content fails
        validation, an exception is raised and no CTO or event is started.

        The profile's apply_defaults() receives the session's mutable context
        dict. The hub passes it through without inspection — the profile owns
        its contents and may update them to maintain session-scoped state.

        The CTO's content_profile field is set to {"id": content_profile,
        "version": profile_version} — a plain serializable dict.

        Args:
            content_profile: Profile identifier string. Must be registered
                in ProfileRegistry.
            content: Profile-conformant content dict. Copied at construction.
            hub_token: Hub-issued token of the submitting Purpose. Required.
                Any registered Purpose (domain or persistence) may submit turns.
            session_id: The session this turn belongs to. Hub mints a UUID
                if not provided.
            profile_version: Version of the profile to use. Defaults to 1.
            request_id: Optional caller correlation key. Not yet enforced in
                v0; reserved for future use.

        Returns:
            The turn_id UUID of the newly started CTO.

        Raises:
            UnauthorizedDispatchError: If hub_token does not resolve to a
                registered Purpose.
            KeyError: If content_profile / profile_version is not registered.
            ValueError: If content does not satisfy the profile contract.
        """
        await self._await_bootstrap_persist()

        reg = self._resolve_registration_for_token_all(hub_token)

        resolved_session_id = session_id if session_id is not None else uuid4()

        profile = ProfileRegistry.get(content_profile, profile_version)
        profile.validate(content, strict=self.strict_profiles)

        resolved_content = profile.apply_defaults(
            content,
            self._session_context(resolved_session_id),
        )

        # Mint the event_id before constructing the CTO so that last_event_id
        # can be set to the cto_started event_id at construction time.
        # This keeps the CTO's version handle and the emitted event in sync
        # without a second write to _ctos after the event is built.
        cto_started_event_id = uuid4()

        cto = CTO(
            turn_id=uuid4(),
            session_id=resolved_session_id,
            created_at_ms=now_ms(),
            content_profile={"id": content_profile, "version": profile_version},
            content=resolved_content,
            last_event_id=cto_started_event_id,
        )
        self._ctos[cto.turn_id] = cto
        _logger.debug(
            "CTO started: turn_id=%s session_id=%s profile=%s submitted_by=%r",
            cto.turn_id,
            cto.session_id,
            content_profile,
            reg.purpose.name,
        )

        event = HubEvent(
            event_type=HubEventType.CTO_STARTED,
            event_id=cto_started_event_id,
            created_at_ms=now_ms(),
            session_id=cto.session_id,
            turn_id=cto.turn_id,
            payload=CTOStartedPayload(
                cto_index=cto.to_index().to_dict(),
                submitted_by_purpose_id=str(reg.purpose.id),
                submitted_by_purpose_name=reg.purpose.name,
            ),
        )

        await self._multicast(event)
        # v0: no DAG yet; dispatch is "all registered purposes for this event"
        return cto.turn_id

    async def close(self, *, reason: str = "normal") -> None:
        """
        Initiate an orderly session shutdown.

        Phase 1 — SESSION_CLOSING broadcast:
            Emitted via _multicast() to all registered Purposes. Domain Purposes
            should use this as their evacuation signal: flush in-flight state,
            submit any final Deltas, and send PURPOSE_COMPLETED to the hub.

        Phase 2 — Quiescence (v0: immediate):
            In v0, the hub does not wait for Purposes to acknowledge the closing
            signal before proceeding. Quiescence detection (waiting for all
            Purposes to send PURPOSE_COMPLETED, or enforcing a timeout) is
            deferred to the DAG layer.

        Phase 3 — SESSION_COMPLETED (persistence-only):
            Written directly to the persistence backend after domain Purposes
            have cleared. Never multicast. This is the final record in the
            event log.

        Args:
            reason: Human-readable shutdown reason (e.g. "normal", "timeout").
                Recorded in the SESSION_CLOSING payload for audit consumers.
        """
        await self._await_bootstrap_persist()

        closing_event = HubEvent(
            event_type=HubEventType.SESSION_CLOSING,
            event_id=uuid4(),
            created_at_ms=now_ms(),
            payload=SessionClosingPayload(
                reason=reason,
                # timeout_ms is None in v0 — quiescence enforcement is a DAG concern.
                timeout_ms=None,
            ),
        )
        await self._multicast(closing_event)

        # v0: no quiescence wait — proceed immediately to SESSION_COMPLETED.
        # The DAG layer will introduce PURPOSE_COMPLETED tracking and timeouts.

        completed_event = HubEvent(
            event_type=HubEventType.SESSION_COMPLETED,
            event_id=uuid4(),
            created_at_ms=now_ms(),
            payload=SessionCompletedPayload(is_last_out=True),
        )
        await self._multicast(completed_event, persistence_only=True)

    def _validate_purpose_event(
        self, event: PurposeEventProtocol
    ) -> tuple[PurposeRegistration, EventPayloadProtocol]:
        """
        Validate a Purpose-originated event and return its registration and payload.

        Validation rules:
          1. hub_token resolves to exactly one current registration
          2. purpose_id matches that registration
          3. purpose_name matches that registration
          4. payload satisfies the EventPayloadProtocol serialization contract
        """
        reg = self._resolve_registration_for_token(event.hub_token)

        if event.purpose_id != reg.purpose.id:
            _logger.warning(
                "purpose event rejected: purpose_id mismatch "
                "(event=%s registered=%s event_type=%s)",
                event.purpose_id,
                reg.purpose.id,
                event.event_type,
            )
            raise UnauthorizedDispatchError(
                "Purpose-originated event rejected — purpose_id does not match "
                "the registration resolved from hub_token."
            )

        if event.purpose_name != reg.purpose.name:
            _logger.warning(
                "purpose event rejected: purpose_name mismatch "
                "(event=%r registered=%r event_type=%s)",
                event.purpose_name,
                reg.purpose.name,
                event.event_type,
            )
            raise UnauthorizedDispatchError(
                "Purpose-originated event rejected — purpose_name does not match "
                "the registration resolved from hub_token."
            )

        payload = event.payload
        payload_dict = payload.as_dict()
        if not isinstance(payload_dict, dict):
            raise TypeError(
                "Purpose-originated event rejected — payload.as_dict() "
                "must return a dict."
            )

        return reg, payload

    async def take_turn(self, event: PurposeEventProtocol) -> UUID | None:
        """
        Canonical ingress path for Purpose-originated events.

        The hub validates the claimed sender against the registration
        resolved from hub_token, then consults event policy to determine
        whether the event triggers built-in hub action.

        Events without built-in handlers are still accepted and processed
        by the hub substrate. Built-in handlers represent built-in hub behavior
        for a subset of events; all others may still be observed by subscribers
        or persistence layers.
        """
        reg, payload = self._validate_purpose_event(event)

        # Try to resolve the event_type as a known PurposeEventType first.
        try:
            event_type = PurposeEventType(event.event_type)
        except ValueError:
            # Not a built-in event type — check the custom registry.
            event_type_str = event.event_type
            if event_type_str in _CUSTOM_EVENT_POLICY:
                if _CUSTOM_EVENT_POLICY[event_type_str]:
                    await self._relay_custom_event(event)
                return None
            raise UnknownEventTypeError(
                f"hub.take_turn: unrecognised event_type {event.event_type!r}"
            )

        policy = _EVENT_POLICY.get(event_type)

        if event_type is PurposeEventType.DELTA_PROPOSAL:
            return await self._handle_delta_proposal(reg, payload)

        if policy is None:
            # Event type is unknown to the hub — not in _EVENT_POLICY at all.
            raise UnknownEventTypeError(
                f"hub.take_turn: unrecognised event_type {event_type!r}"
            )

        # Known event type with no built-in handler — accepted, no action taken.
        return None

    async def _relay_custom_event(self, event: PurposeEventProtocol) -> None:
        """Wrap a custom Purpose event as a HubEvent and multicast it."""
        hub_event = HubEvent(
            event_type=event.event_type,  # str; accepted via HubEvent.event_type: HubEventType | str
            event_id=event.event_id,
            created_at_ms=event.created_at_ms,
            payload=event.payload,
        )
        await self._multicast(hub_event)

    async def _handle_delta_proposal(
        self,
        reg: PurposeRegistration,
        payload: EventPayloadProtocol,
    ) -> UUID:
        """
        Built-in handler for DELTA_PROPOSAL Purpose events.
        """
        # At this point we know the payload must contain a Delta.
        delta_payload = cast(DeltaProposalPayload, payload)
        delta: Delta = delta_payload.delta

        return await self._merge_delta(delta)

    async def _merge_delta(self, delta: Delta) -> UUID:
        """
        Validate and merge a Purpose-proposed Delta into canonical CTO state.

        On validation failure, emits DELTA_REJECTED (for the event log) then
        re-raises the underlying exception so callers are not silently swallowed.

        This is a hub-internal mutation helper. Purposes submit proposals via
        hub.take_turn(); validated input routing calls _merge_delta().
        """
        cto = self._ctos.get(delta.turn_id)
        if cto is None:
            _logger.warning(
                "_merge_delta: unknown turn_id %r (purpose=%r delta_id=%s)",
                delta.turn_id,
                delta.purpose_name,
                delta.delta_id,
            )
            reason = f"unknown turn_id {delta.turn_id!r}"
            await self._emit_delta_rejected(delta, reason)
            raise KeyError(f"_merge_delta: {reason}")

        for key, val in delta.patch.items():
            if not isinstance(val, list):
                _logger.warning(
                    "_merge_delta: non-list patch value rejected "
                    "(key=%r type=%s purpose=%r turn_id=%s)",
                    key,
                    type(val).__name__,
                    delta.purpose_name,
                    delta.turn_id,
                )
                reason = (
                    f"patch[{key!r}] must be a list, "
                    f"got {type(val).__name__!r} — hub enforces append-only semantics"
                )
                await self._emit_delta_rejected(delta, reason)
                raise ValueError(f"_merge_delta: {reason}")

        delta_merged_event_id = uuid4()

        namespace = delta.purpose_name
        existing_obs = dict(cto.observations)
        existing_ns = list(existing_obs.get(namespace, []))
        for key, items in delta.patch.items():
            existing_ns.extend({"key": key, "value": v} for v in items)
        existing_obs[namespace] = existing_ns

        updated_cto = CTO(
            turn_id=cto.turn_id,
            session_id=cto.session_id,
            created_at_ms=cto.created_at_ms,
            content_profile=cto.content_profile,
            content=cto.content,
            observations=existing_obs,
            last_event_id=delta_merged_event_id,
        )
        self._ctos[updated_cto.turn_id] = updated_cto
        _logger.debug(
            "delta merged: turn_id=%s purpose=%r last_event_id=%s",
            updated_cto.turn_id,
            delta.purpose_name,
            updated_cto.last_event_id,
        )

        event = HubEvent(
            event_type=HubEventType.DELTA_MERGED,
            event_id=delta_merged_event_id,
            created_at_ms=now_ms(),
            session_id=updated_cto.session_id,
            turn_id=updated_cto.turn_id,
            payload=DeltaMergedPayload(
                delta=delta.to_dict(),
                cto_index=updated_cto.to_index().to_dict(),
            ),
        )
        await self._multicast(event)
        return delta_merged_event_id

    async def _emit_delta_rejected(self, delta: Delta, reason: str) -> None:
        """
        Emit a DELTA_REJECTED event for a failed merge attempt.

        This is a provenance record — it does not replace the exception that
        the caller raises after this method returns. The event is multicast
        so that Purposes and the persistence backend both see the rejection.
        """
        event = HubEvent(
            event_type=HubEventType.DELTA_REJECTED,
            event_id=uuid4(),
            created_at_ms=now_ms(),
            session_id=None,
            turn_id=delta.turn_id,
            payload=DeltaRejectedPayload(
                delta_dict=delta.to_dict(),
                reason=reason,
            ),
        )
        await self._multicast(event)

    async def _multicast(
        self, event: HubEvent, *, persistence_only: bool = False
    ) -> None:
        """
        Deliver a hub-authored event: persistence first, then broadcast.

        Phase 1 — Persistence (unconditional):
            If a persistence Purpose is registered, write_event() is called
            before any domain Purpose receives the event. Failure raises
            PersistenceFailureError and halts delivery — no domain Purpose
            receives an event that was not persisted.

        Phase 2 — Broadcast (domain Purposes):
            Skipped when persistence_only=True. Otherwise, each registered
            domain Purpose receives a per-recipient envelope stamped with its
            own hub_token and downlink_signature.

        persistence_only=True is used for SESSION_COMPLETED, which is the
        final record and must not be delivered to domain Purposes.

        v0: naive broadcast to all registered Purposes — no subscription
        filtering or DAG eligibility gating yet.
        """
        # Phase 1: persistence write before any domain delivery.
        if self.persistence_purpose is not None:
            p = self.persistence_purpose
            try:
                await p.write_event(event)
            except Exception as exc:
                _logger.critical(
                    "persistence write failed: persister=%r event_id=%s event_type=%s — "
                    "halting delivery (no domain Purpose will receive this event)",
                    p.name,
                    event.event_id,
                    event.event_type,
                    exc_info=exc,
                )
                raise PersistenceFailureError(
                    f"Persistence write failed for event {event.event_id} "
                    f"(persister={p.name!r}): {exc}",
                    persister_name=p.name,
                    event_id=event.event_id,
                ) from exc

        # Phase 2: per-recipient broadcast to domain Purposes.
        if persistence_only:
            return

        for reg in self.registrations.values():
            addressed = HubEvent(
                event_type=event.event_type,
                event_id=event.event_id,
                created_at_ms=event.created_at_ms,
                session_id=event.session_id,
                turn_id=event.turn_id,
                payload=event.payload,
                hub_token=reg.token,
                downlink_signature=reg.downlink_signature,
            )
            await reg.purpose.take_turn(addressed)
