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
import logging
import secrets
import time
import warnings
from dataclasses import dataclass, field
from typing import Any, cast
from uuid import UUID, uuid4

from turnturnturn.errors import UnauthorizedDispatchError

from .base_purpose import BasePurpose, SessionOwnerPurpose
from .cto import CTO
from .delta import Delta
from .errors import HubClosedError, PersistenceFailureError, UnknownEventTypeError
from .events import (
    CTOStartedPayload,
    DeltaMergedPayload,
    DeltaRejectedPayload,
    HubEvent,
    HubEventType,
    PurposeEventType,
    SessionClosePendingPayload,
    SessionClosingPayload,
)
from .events.hub_events import DeltaProposalPayload
from .events.purpose_events import EndSessionPayload, PurposeCompletedPayload
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
    PurposeEventType.PURPOSE_STARTED: _EventPolicy(handler="_handle_purpose_started"),
    PurposeEventType.SESSION_STARTED: _EventPolicy(handler="_handle_session_started"),
    PurposeEventType.END_SESSION: _EventPolicy(handler="_handle_end_session"),
    PurposeEventType.PURPOSE_COMPLETED: _EventPolicy(
        handler="_handle_purpose_completed"
    ),
    PurposeEventType.SESSION_COMPLETED: _EventPolicy(
        handler="_handle_session_completed"
    ),
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
    session_owner_purpose: SessionOwnerPurpose | None = field(default=None, repr=False)
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
    _bootstrap_owner_task: asyncio.Task[None] | None = field(
        default=None, init=False, repr=False
    )
    _session_owners: dict[UUID, UUID] = field(
        default_factory=dict, init=False, repr=False
    )
    _session_codes: dict[UUID, str] = field(
        default_factory=dict, init=False, repr=False
    )
    _closing_sessions: dict[UUID, set[UUID]] = field(
        default_factory=dict, init=False, repr=False
    )
    _is_closing: bool = field(default=False, init=False, repr=False)
    _closing_session_id: UUID | None = field(default=None, init=False, repr=False)
    _is_closed: bool = field(default=False, init=False, repr=False)
    _closed_session_id: UUID | None = field(default=None, init=False, repr=False)
    librarian: Librarian = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Wire the librarian to the hub's CTO store after dataclass init."""
        self.librarian = Librarian(_ctos=self._ctos)

    @classmethod
    def start(
        cls,
        persistence_purpose: CTOPersistencePurposeProtocol,
        session_owner_purpose: SessionOwnerPurpose,
        *,
        strict_profiles: bool = False,
    ) -> "TTT":
        """
        Start a new TTT hub and ensure built-in profiles are loaded.

        persistence_purpose and session_owner_purpose are required startup
        participants. The hub will not start without both a registered
        persistence backend and an explicit session-owner Purpose.

        Emits session_started directly to the persistence Purpose as its
        first act — before any other registration or dispatch. This event
        is the first record in the event log and carries hub provenance
        (hub_id, ttt_version, persister identity, is_durable).

        Registers the startup session owner before returning. That owner is
        the only Purpose permitted to create the first turn for a new session.

        Current implementation note:
            `session_started` is written through a special bootstrap path here.
            The architecture docs describe a stricter long-term direction in
            which bootstrap roles and lifecycle provenance become more fully
            mesh-native. See ``docs/architecture/bootstrap_lifecycle.md``.

        A UserWarning is issued if persistence_purpose.is_durable is False.
        Non-durable backends (e.g. InMemoryPersistencePurpose) are valid
        for development but should not be used in production.

        Calls ProfileRegistry.load_defaults() to register built-in profiles
        if not already present. Safe to call multiple times in the same process.

        Args:
            persistence_purpose: A CTOPersistencePurposeProtocol implementor.
                Must be provided; there is no default.
            session_owner_purpose: Explicit startup owner for any new session
                created on this hub. Must be a SessionOwnerPurpose instance.
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
        if not isinstance(session_owner_purpose, SessionOwnerPurpose):
            raise TypeError(
                "TTT.start() requires a SessionOwnerPurpose instance as "
                "session_owner_purpose; "
                f"got {type(session_owner_purpose)!r}."
            )
        if isinstance(session_owner_purpose, CTOPersistencePurposeProtocol):
            raise TypeError(
                "session_owner_purpose must be distinct from the persistence Purpose."
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
            session_owner_purpose=session_owner_purpose,
        )
        # Bootstrap the persister: assign credentials, emit session_started.
        # This is synchronous because start() is a classmethod and no event
        # loop is available at this point. The persister's write_event() is
        # called via a synchronous shim for this one bootstrap event only.
        hub._bootstrap_persister()
        hub._bootstrap_session_owner()
        return hub

    @classmethod
    def register_event_type(cls, event_type: str, *, multicast: bool = True) -> None:
        """Register a custom Purpose-originated event type with the hub relay.

        Registered types are accepted by `take_turn()`. When `multicast=True`
        (default), the event is wrapped as a `HubEvent` with `event_type: str`
        and delivered to all registered Purposes and the persistence backend via
        `_relay_custom_event()`. When `multicast=False`, the event is accepted
        and persisted but not delivered to other Purposes.

        `event_type` must be a dotted-namespace string, e.g. `"adjacency.stimulus"`.
        Constraints:

        - Non-empty.
        - Alphanumeric after stripping `.` and `_` (no other special characters).
        - Cannot start or end with `.`.

        Re-registering the same `event_type` with the same `multicast` value is a
        no-op. Re-registering with a different `multicast` value raises `ValueError`.

        This is a class-level call that writes to the module-level
        `_CUSTOM_EVENT_POLICY` dict. It is safe to call multiple times (idempotent
        for identical arguments). Call before the first `session.start()`.
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
        existing = _CUSTOM_EVENT_POLICY.get(event_type)
        if existing is not None and existing != multicast:
            raise ValueError(
                f"event_type {event_type!r} is already registered with multicast={existing!r}; "
                f"cannot re-register with multicast={multicast!r}"
            )
        _CUSTOM_EVENT_POLICY[event_type] = multicast

    def _bootstrap_persister(self) -> None:
        """
        Assign route credentials to the persistence Purpose and bootstrap its
        lifecycle provenance.

        Called once by TTT.start() before any other registration or dispatch.
        Durable persistence Purposes may emit `session_started`; all
        persistence Purposes emit `purpose_started`.

        This method is synchronous because TTT.start() is a classmethod with
        no event loop. If a loop is already running, the bootstrap emission is
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
            p._assign_hub(self)

        self._run_bootstrap_coroutine(
            self._emit_bootstrap_persistence_started(),
            task_attr="_bootstrap_persist_task",
        )

    async def _emit_bootstrap_persistence_started(self) -> None:
        """Let the registered persistence purpose author its own startup facts."""
        p = self.persistence_purpose
        assert p is not None
        if isinstance(p, BasePurpose):
            await p.emit_session_started(strict_profiles=self.strict_profiles)  # type: ignore[attr-defined]
            await p.announce_started(is_persistence_purpose=True)

    def _bootstrap_session_owner(self) -> None:
        """Bind the startup session owner before normal registration begins."""
        owner = self.session_owner_purpose
        assert owner is not None  # invariant: enforced by start()
        self._register_purpose(owner)
        self._run_bootstrap_coroutine(
            self._emit_bootstrap_owner_started(owner),
            task_attr="_bootstrap_owner_task",
        )

    async def _emit_bootstrap_owner_started(
        self,
        owner: SessionOwnerPurpose,
    ) -> None:
        """Emit the owner's registration provenance after session_started is durable."""
        persist_task = self._bootstrap_persist_task
        if persist_task is not None:
            await persist_task
        await owner.announce_started()

    def _run_bootstrap_coroutine(
        self,
        coro: Any,
        *,
        task_attr: str,
    ) -> None:
        """Run a bootstrap coroutine synchronously or schedule it on a running loop."""
        try:
            loop = asyncio.get_running_loop()
            setattr(self, task_attr, loop.create_task(coro))
        except RuntimeError:
            asyncio.run(coro)

    async def _await_bootstrap_ready(self) -> None:
        """
        Ensure bootstrap persistence and owner admission side effects have completed.

        This matters when TTT.start() is called inside an already-running event
        loop and bootstrap coroutines had to be scheduled as tasks. All later
        async hub operations await those tasks first so startup ordering remains
        deterministic for persistence and registration.
        """
        persist_task = self._bootstrap_persist_task
        if persist_task is not None:
            self._bootstrap_persist_task = None
            try:
                await persist_task
            except Exception as exc:
                p = self.persistence_purpose
                name = p.name if p is not None else "unknown"
                raise PersistenceFailureError(
                    "Persistence-purpose bootstrap failed for startup lifecycle events "
                    f"(persister={name!r}): {exc}",
                    persister_name=name,
                    event_id=None,
                ) from exc

        owner_task = self._bootstrap_owner_task
        if owner_task is not None:
            self._bootstrap_owner_task = None
            await owner_task

    def _register_purpose(
        self,
        purpose: PurposeProtocol,
        *,
        subscriptions: list[dict[str, Any]] | None = None,
    ) -> PurposeRegistration:
        """Bind a Purpose to this hub, assign credentials, and store its registration."""
        token: str | None = None
        downlink_signature: str | None = None

        if isinstance(purpose, BasePurpose):
            token = secrets.token_hex(16)
            downlink_signature = self._build_downlink_signature(token, purpose.id)
            purpose._assign_token(token)
            purpose._assign_downlink_signature(downlink_signature)
            purpose._assign_hub(self)

        reg = PurposeRegistration(
            purpose=purpose,
            token=token,
            downlink_signature=downlink_signature,
            subscriptions=subscriptions or [],
        )
        self.registrations[purpose.id] = reg
        _logger.debug(
            "purpose registered: name=%r id=%s token_assigned=%s",
            purpose.name,
            purpose.id,
            token is not None,
        )
        return reg

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

        Architectural note:
            The intended lifecycle model treats registration as immediate and
            `purpose_started` primarily as provenance and mesh information,
            not as a second handshake required to complete admission.
        """
        await self._await_bootstrap_ready()
        self._ensure_accepting_new_work("start_purpose")
        self._register_purpose(purpose, subscriptions=subscriptions)
        if isinstance(purpose, BasePurpose):
            await purpose.announce_started(
                is_persistence_purpose=isinstance(
                    purpose, CTOPersistencePurposeProtocol
                )
            )

    async def start_turn(
        self,
        content_profile: str,
        content: dict[str, Any],
        hub_token: str,
        *,
        session_id: UUID | None = None,
        session_code: str | None = None,
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

        Session ownership:
            The current ownership rule is intentionally simple: the registered
            Purpose that creates the first turn for a session is recorded as
            that session's owner. Hub-side lifecycle actions such as
            `end_session` authorization are checked against that binding.

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
            session_code: Optional caller-defined stable session code persisted
                in session lifecycle events.
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
        await self._await_bootstrap_ready()
        self._ensure_accepting_new_work("start_turn")

        reg = self._resolve_registration_for_token_all(hub_token)

        resolved_session_id = session_id if session_id is not None else uuid4()
        if session_code is not None and not session_code:
            raise ValueError("session_code must be a non-empty string when provided")

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
        if resolved_session_id not in self._session_owners:
            owner = self.session_owner_purpose
            if owner is None or reg.purpose.id != owner.id:
                raise UnauthorizedDispatchError(
                    "start_turn() rejected — only the startup session owner Purpose "
                    "may create the first turn for a new session."
                )
            self._session_owners[resolved_session_id] = reg.purpose.id
        if session_code is not None:
            self._session_codes[resolved_session_id] = session_code
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
        Legacy shutdown entry point.

        New shutdown should proceed from a session owner's `end_session()`
        request. This method remains as a compatibility shim that only emits
        `session_closing`.

        Args:
            reason: Human-readable shutdown reason (e.g. "normal", "timeout").
                Recorded in the SESSION_CLOSING payload for audit consumers.
        """
        await self._await_bootstrap_ready()
        self._ensure_accepting_new_work("close")

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

    async def _route_purpose_event_to_persistence(
        self, event: PurposeEventProtocol
    ) -> None:
        """
        Route an accepted Purpose-originated event to the persistence Purpose.

        This preserves the invariant that accepted mesh ingress reaches the
        persistence layer before any built-in hub behavior derived from it.
        Persistence-authored events are excluded: those are written by the
        persistence Purpose as part of emission before they reach hub ingress.
        """
        p = self.persistence_purpose
        if p is None:
            return
        try:
            await p.write_event(event)
        except Exception as exc:
            _logger.critical(
                "persistence write failed: persister=%r event_id=%s event_type=%s — "
                "halting handling of accepted purpose event",
                p.name,
                event.event_id,
                event.event_type,
                exc_info=exc,
            )
            raise PersistenceFailureError(
                f"Persistence-purpose write failed for accepted purpose event {event.event_id} "
                f"(persister={p.name!r}): {exc}",
                persister_name=p.name,
                event_id=event.event_id,
            ) from exc

    async def _emit_session_close_pending(self, session_id: UUID) -> None:
        """Send the all-clear event that only the persistence layer remains active."""
        event = HubEvent(
            event_type=HubEventType.SESSION_CLOSE_PENDING,
            event_id=uuid4(),
            created_at_ms=now_ms(),
            session_id=session_id,
            payload=SessionClosePendingPayload(
                remaining_domain_purposes=0,
                session_code=self._session_codes.get(session_id),
            ),
        )
        await self._multicast(
            event,
            persistence_only=True,
            persist_before_dispatch=False,
            deliver_to_persistence=True,
        )

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
        reg = self._resolve_registration_for_token_all(event.hub_token)

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
        # Try to resolve the event_type as a known PurposeEventType first.
        try:
            event_type = PurposeEventType(event.event_type)
        except ValueError:
            # Not a built-in event type — check the custom registry.
            event_type_str = event.event_type
            if event_type_str in _CUSTOM_EVENT_POLICY:
                self._ensure_accepting_event("take_turn", event_type_str)
                reg, payload = self._validate_purpose_event(event)
                if _CUSTOM_EVENT_POLICY[event_type_str]:
                    await self._relay_custom_event(event)
                return None
            self._ensure_accepting_event("take_turn", event.event_type)
            raise UnknownEventTypeError(
                f"hub.take_turn: unrecognised event_type {event.event_type!r}"
            )

        self._ensure_accepting_event("take_turn", event_type.value)
        reg, payload = self._validate_purpose_event(event)
        policy = _EVENT_POLICY.get(event_type)
        p = self.persistence_purpose
        if p is None or reg.purpose.id != p.id:
            await self._route_purpose_event_to_persistence(event)

        if event_type is PurposeEventType.DELTA_PROPOSAL:
            return await self._handle_delta_proposal(reg, payload)
        if event_type is PurposeEventType.PURPOSE_STARTED:
            return await self._handle_purpose_started(event)
        if event_type is PurposeEventType.SESSION_STARTED:
            return await self._handle_session_started(reg)
        if event_type is PurposeEventType.END_SESSION:
            return await self._handle_end_session(reg, payload)
        if event_type is PurposeEventType.PURPOSE_COMPLETED:
            return await self._handle_purpose_completed(reg, payload)
        if event_type is PurposeEventType.SESSION_COMPLETED:
            return await self._handle_session_completed(reg, event)

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

    async def _relay_purpose_event(self, event: PurposeEventProtocol) -> None:
        """Wrap an accepted Purpose event as a HubEvent and multicast it without re-writing it."""
        hub_event = HubEvent(
            event_type=event.event_type,
            event_id=event.event_id,
            created_at_ms=event.created_at_ms,
            session_id=getattr(event, "session_id", None),
            turn_id=getattr(event, "turn_id", None),
            payload=event.payload,
        )
        await self._multicast(hub_event, persist_before_dispatch=False)

    async def _handle_purpose_started(self, event: PurposeEventProtocol) -> None:
        """Relay purpose_started onto the downlink without re-routing it to persistence."""
        await self._relay_purpose_event(event)
        return None

    async def _handle_session_started(self, reg: PurposeRegistration) -> None:
        """Accept session_started only from the durable persistence purpose."""
        p = self.persistence_purpose
        if p is None or reg.purpose.id != p.id or not p.is_durable:
            raise UnauthorizedDispatchError(
                "session_started rejected — only the durable persistence Purpose may emit it."
            )
        return None

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

    async def _handle_end_session(
        self,
        reg: PurposeRegistration,
        payload: EventPayloadProtocol,
    ) -> None:
        """Authorize and initiate closing for the session owned by this Purpose."""
        end_payload = cast(EndSessionPayload, payload)
        session_id = UUID(end_payload.session_id)
        owner_id = self._session_owners.get(session_id)
        if owner_id is None:
            raise KeyError(f"unknown session_id {end_payload.session_id!r}")
        if self._is_closing:
            if self._closing_session_id == session_id:
                return None
            raise HubClosedError(
                "end_session rejected — the hub is already closing a different session."
            )
        if owner_id != reg.purpose.id:
            raise UnauthorizedDispatchError(
                "end_session rejected — only the session-owning Purpose may close the session."
            )
        self._is_closing = True
        self._closing_session_id = session_id
        self._closing_sessions[session_id] = set(self.registrations.keys())
        closing_event = HubEvent(
            event_type=HubEventType.SESSION_CLOSING,
            event_id=uuid4(),
            created_at_ms=now_ms(),
            session_id=session_id,
            payload=SessionClosingPayload(
                reason=end_payload.reason,
                timeout_ms=None,
                session_code=self._session_codes.get(session_id),
            ),
        )
        await self._multicast(closing_event)
        return None

    async def _handle_purpose_completed(
        self,
        reg: PurposeRegistration,
        payload: EventPayloadProtocol,
    ) -> None:
        """Track Purpose acknowledgements and finish once all domain Purposes clear."""
        completed_payload = cast(PurposeCompletedPayload, payload)
        session_id = UUID(completed_payload.session_id)
        pending = self._closing_sessions.get(session_id)
        if pending is None:
            return None

        pending.discard(reg.purpose.id)
        if pending:
            return None

        del self._closing_sessions[session_id]
        await self._emit_session_close_pending(session_id)
        return None

    async def _handle_session_completed(
        self,
        reg: PurposeRegistration,
        event: PurposeEventProtocol,
    ) -> None:
        """Accept final session completion only from the durable persistence purpose."""
        p = self.persistence_purpose
        if p is None or reg.purpose.id != p.id or not p.is_durable:
            raise UnauthorizedDispatchError(
                "session_completed rejected — only the durable persistence Purpose may emit it."
            )
        self._is_closing = False
        self._closing_session_id = None
        self._is_closed = True
        self._closed_session_id = getattr(event, "session_id", None)
        return None

    def _ensure_accepting_new_work(self, operation: str) -> None:
        """Reject new registration/turn/legacy-close operations once shutdown begins."""
        if self._is_closed:
            session_id = self._closed_session_id
            session_info = f" session_id={session_id}" if session_id is not None else ""
            raise HubClosedError(
                f"TTT.{operation}() rejected — the hub has already accepted "
                f"session_completed and is closed.{session_info}"
            )
        if not self._is_closing:
            return
        session_id = self._closing_session_id
        session_info = f" session_id={session_id}" if session_id is not None else ""
        raise HubClosedError(
            f"TTT.{operation}() rejected — the hub is already closing and "
            f"accepts no new work.{session_info}"
        )

    def _ensure_accepting_event(self, operation: str, event_type: str) -> None:
        """Reject non-shutdown ingress once the hub is closing or closed."""
        if self._is_closed:
            session_id = self._closed_session_id
            session_info = f" session_id={session_id}" if session_id is not None else ""
            raise HubClosedError(
                f"TTT.{operation}() rejected event_type={event_type!r} — the hub has "
                f"already accepted session_completed and is closed.{session_info}"
            )
        if not self._is_closing:
            return
        allowed = {
            PurposeEventType.END_SESSION.value,
            PurposeEventType.PURPOSE_COMPLETED.value,
            PurposeEventType.SESSION_COMPLETED.value,
        }
        if event_type in allowed:
            return
        session_id = self._closing_session_id
        session_info = f" session_id={session_id}" if session_id is not None else ""
        raise HubClosedError(
            f"TTT.{operation}() rejected event_type={event_type!r} — the hub is "
            f"closing and only accepts purpose_completed or session_completed "
            f"(plus duplicate end_session for the active session).{session_info}"
        )

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
        self,
        event: HubEvent,
        *,
        persistence_only: bool = False,
        persist_before_dispatch: bool = True,
        deliver_to_persistence: bool = False,
    ) -> None:
        """
        Deliver a hub-authored event by routing it in the configured order.

        By default, the event is first routed to the persistence Purpose's
        write path, then broadcast to registered domain Purposes. Some
        coordination events intentionally override that default:

        - purpose-authored lifecycle facts that have already been routed to
          persistence should be relayed without a second persistence write
        - session_close_pending should be delivered to the persistence Purpose
          as a downlink event so it can author final completion facts

        Phase 2 — Broadcast (domain Purposes):
            Skipped when persistence_only=True. Otherwise, each registered
            domain Purpose receives a per-recipient envelope stamped with its
            own hub_token and downlink_signature.

        v0: naive broadcast to all registered Purposes — no subscription
        filtering or DAG eligibility gating yet.
        """
        if persist_before_dispatch and self.persistence_purpose is not None:
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

        if deliver_to_persistence and self.persistence_purpose is not None:
            p = self.persistence_purpose
            if isinstance(p, BasePurpose):
                addressed = HubEvent(
                    event_type=event.event_type,
                    event_id=event.event_id,
                    created_at_ms=event.created_at_ms,
                    session_id=event.session_id,
                    turn_id=event.turn_id,
                    payload=event.payload,
                    hub_token=p.token,
                    downlink_signature=p.downlink_signature,
                )
                await p.take_turn(addressed)

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
