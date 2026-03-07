"""TTT hub runtime — authoritative CTO creation, Delta merge, and event emission."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from .base_purpose import BasePurpose
from .cto import CTO
from .delta import Delta
from .events import HubEvent, HubEventType, payload_cto_created, payload_delta_merged
from .profile import Profile, ProfileRegistry
from .protocols import PurposeProtocol
from .registry import PurposeRegistration

"""
CTO creation boundary:
start_turn(session_id, content_profile, content, ...)
    -> look up Profile from ProfileRegistry
    -> validate content against profile contract
    -> apply profile defaults (profile reads/writes opaque session context)
    -> create CTO with content_profile = {"id": ..., "version": ...}
    -> emit cto_created
    -> dispatch to registered Purposes
"""


def now_ms() -> int:
    """Return current Unix time in milliseconds. Used for CTO and event timestamps."""
    return int(time.time() * 1000)


@dataclass
class TTT:
    """
    TurnTurnTurn hub runtime.

    The hub is the sole authority for CTO creation, Delta merge, and event
    emission. All content ingress goes through start_turn(); nothing constructs
    CTOs directly.

    Instantiate via TTT.create() — do not construct directly. TTT.create()
    ensures built-in profiles are registered before the hub is used.

    Profile lookup delegates to the process-scoped ProfileRegistry class.
    Custom profiles are registered via TTT.register_profile(), which delegates
    to ProfileRegistry.register().

    The hub maintains an opaque per-session context dict for each active
    session and passes it to Profile.apply_defaults() as a mutable dict.
    The hub never inspects context contents — profiles own them entirely.
    This allows profiles to maintain session-scoped state (e.g. speaker
    ordinals for label defaults) without leaking domain knowledge into the hub.
    """

    registrations: dict[UUID, PurposeRegistration]
    strict_profiles: bool = False
    _session_contexts: dict[UUID, dict[str, Any]] = field(
        default_factory=dict, init=False, repr=False
    )
    # Canonical CTO store: turn_id → CTO.
    # The hub is the sole writer. CTOs are replaced (not mutated) on Delta merge
    # because CTO is frozen — a new instance is constructed with updated observations.
    _ctos: dict[UUID, CTO] = field(default_factory=dict, init=False, repr=False)

    # TODO(delta-versioning): When CTO.last_event_id and Delta.based_on_event_id
    # are added, merge_delta() should compare delta.based_on_event_id against
    # cto.last_event_id before merging. Mismatch = Purpose was reasoning about
    # stale state. Initial handling policy (reject / warn / resolver dispatch)
    # to be decided by Adjacency integration requirements.

    @classmethod
    def create(cls, *, strict_profiles: bool = False) -> "TTT":
        """
        Construct a new TTT hub and ensure built-in profiles are loaded.

        Calls ProfileRegistry.load_defaults() to register built-in profiles
        if not already present. Safe to call multiple times in the same process.

        Args:
            strict_profiles: If True, enforce strict key validation on all
                profiles at start_turn() time.
        """
        ProfileRegistry.load_defaults()
        return cls(registrations={}, strict_profiles=strict_profiles)

    @staticmethod
    def register_profile(profile: Profile) -> None:
        """
        Register a custom Profile with the process-scoped ProfileRegistry.

        Allows consuming projects to add profiles without modifying core
        modules. Overwrites any existing registration for the same
        (profile_id, version) pair.

        Args:
            profile: The Profile to register.
        """
        ProfileRegistry.register(profile)

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

    async def register_purpose(
        self,
        purpose: PurposeProtocol,
        *,
        subscriptions: list[dict[str, Any]] | None = None,
    ) -> None:
        """
        Register a Purpose with the hub and assign its hub token.

        After registration, the Purpose will receive HubEvents via take_turn()
        on each multicast. Re-registering an existing purpose.id overwrites the
        prior registration and issues a new token.

        If the Purpose is a BasePurpose instance, a cryptographically random
        token is generated and assigned via _assign_token(). This token is
        embedded in every HubEvent dispatched to that Purpose, allowing
        BasePurpose.take_turn() to reject events from any other source.

        Purposes that are not BasePurpose subclasses (e.g. test doubles
        implementing PurposeProtocol directly) are registered without token
        assignment — they receive events without validation.

        Args:
            purpose: The Purpose instance to register. Must satisfy PurposeProtocol.
            subscriptions: Event filter hints for future subscription matching.
                Currently unused in v0 — all registered Purposes receive all
                events. Will be enforced once the DAG/subscription layer lands.
        """
        # v0: in-memory registry only. Later: emit PURPOSE_REGISTERED, persist, auth.
        token: str | None = None
        if isinstance(purpose, BasePurpose):
            token = secrets.token_hex(16)
            purpose._assign_token(token)

        subs = subscriptions or []
        self.registrations[purpose.id] = PurposeRegistration(
            purpose=purpose,
            token=token,
            subscriptions=subs,
        )

    async def start_turn(
        self,
        session_id: UUID,
        content_profile: str,
        content: dict[str, Any],
        *,
        profile_version: int = 1,
        request_id: str | None = None,
        submitted_by_label: str | None = None,
    ) -> UUID:
        """
        Look up the profile, validate content, apply defaults, create a CTO,
        emit cto_created, then dispatch to registered Purposes.

        This is the sole ingress point for canonical turn creation. The hub is
        the only entity permitted to construct CTOs. If the profile is unknown
        or content fails validation, an exception is raised and no CTO or
        event is created.

        The profile's apply_defaults() receives the session's mutable context
        dict. The hub passes it through without inspection — the profile owns
        its contents and may update them to maintain session-scoped state.

        The CTO's content_profile field is set to {"id": content_profile,
        "version": profile_version} — a plain serializable dict.

        Args:
            session_id: The session this turn belongs to.
            content_profile: Profile identifier string. Must be registered
                in ProfileRegistry.
            content: Profile-conformant content dict. Copied at construction.
            profile_version: Version of the profile to use. Defaults to 1.
            request_id: Optional caller correlation key. Not yet enforced in
                v0; reserved for future use.
            submitted_by_label: Optional provenance label for non-Purpose
                callers. Recorded in the cto_created event payload.

        Returns:
            The turn_id UUID of the newly created CTO.

        Raises:
            KeyError: If content_profile / profile_version is not registered.
            ValueError: If content does not satisfy the profile contract.
        """
        profile = ProfileRegistry.get(content_profile, profile_version)
        profile.validate(content, strict=self.strict_profiles)

        resolved_content = profile.apply_defaults(
            content,
            self._session_context(session_id),
        )

        cto = CTO(
            turn_id=uuid4(),
            session_id=session_id,
            created_at_ms=now_ms(),
            content_profile={"id": content_profile, "version": profile_version},
            content=resolved_content,
        )
        self._ctos[cto.turn_id] = cto

        event = HubEvent(
            event_type=HubEventType.CTO_CREATED,
            event_id=uuid4(),
            created_at_ms=now_ms(),
            session_id=cto.session_id,
            turn_id=cto.turn_id,
            payload=payload_cto_created(
                cto_index_dict=cto.to_index().to_dict(),
                submitted_by_label=submitted_by_label,
            ),
        )

        await self._multicast(event)
        # v0: no DAG yet; dispatch is "all registered purposes for this event"
        return cto.turn_id

    async def merge_delta(self, delta: Delta) -> UUID:
        """
        Validate and merge a purpose-proposed Delta into canonical CTO state.

        The hub is the sole authority for writing to canonical state. Purposes
        propose changes via Deltas; this method decides what becomes canonical.

        Merge semantics are append-only: each key in delta.patch is treated as
        a list of observations to append to the CTO's observation namespace
        owned by the proposing Purpose (keyed by purpose_name). Values must be
        lists — the hub extends the existing list, never replaces it.

        On success, the canonical CTO is updated and a DELTA_MERGED event is
        emitted and multicast to all registered Purposes.

        Args:
            delta: The proposed change. Must reference a known turn_id.

        Returns:
            The event_id of the emitted DELTA_MERGED HubEvent.

        Raises:
            KeyError: If delta.turn_id does not reference a known CTO.
            ValueError: If any patch value is not a list (append-only contract).
        """
        cto = self._ctos.get(delta.turn_id)
        if cto is None:
            raise KeyError(f"merge_delta: unknown turn_id {delta.turn_id!r}")

        # Validate patch shape: all values must be lists (append-only contract).
        for key, val in delta.patch.items():
            if not isinstance(val, list):
                raise ValueError(
                    f"merge_delta: patch[{key!r}] must be a list, "
                    f"got {type(val).__name__!r} — hub enforces append-only semantics"
                )

        # Build updated observations: purpose_name namespace, append-only.
        # CTO is frozen, so we construct a new instance with updated observations.
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
        )
        self._ctos[updated_cto.turn_id] = updated_cto

        event_id = uuid4()
        event = HubEvent(
            event_type=HubEventType.DELTA_MERGED,
            event_id=event_id,
            created_at_ms=now_ms(),
            session_id=updated_cto.session_id,
            turn_id=updated_cto.turn_id,
            payload=payload_delta_merged(
                delta_dict=delta.to_dict(),
                cto_index_dict=updated_cto.to_index().to_dict(),
            ),
        )
        await self._multicast(event)
        return event_id

    def get_cto(self, turn_id: UUID) -> CTO | None:
        """
        Return the current canonical CTO for turn_id, or None if unknown.

        This is the intended read path for Purposes that need full CTO state
        — content, observations, profile accessors. HubEvent payloads carry
        only a CTOIndex (a lightweight routing reference); Purposes call this
        method when they need more.

        ctoPersistP is the canonical consumer: it receives a CTOIndex in the
        event payload, calls get_cto(), and persists the full canonical state.

        The returned CTO reflects the hub's current canonical state at the
        moment of the call — for delta_merged events, this is the post-merge
        state. The hub is the sole authority; do not cache the result across
        event boundaries.

        Args:
            turn_id: The turn_id of the CTO to retrieve.

        Returns:
            The canonical CTO, or None if turn_id is not known to this hub.
        """
        return self._ctos.get(turn_id)

    async def _multicast(self, event: HubEvent) -> None:
        """
        Broadcast a HubEvent to all registered Purposes.

        Constructs a per-recipient envelope for each Purpose, stamping
        hub_token with the token assigned to that Purpose at registration.
        This ensures BasePurpose.take_turn() can validate that the event
        originated from this hub and not from a point-to-point call.

        Purposes registered without a token (e.g. bare PurposeProtocol
        implementations in tests) receive the event with hub_token=None.

        v0: naive broadcast — every registered Purpose receives every event.

        Later:
          - subscription matching by event_type (+ filters)
          - DAG eligibility gating
        """
        for reg in self.registrations.values():
            addressed = HubEvent(
                event_type=event.event_type,
                event_id=event.event_id,
                created_at_ms=event.created_at_ms,
                session_id=event.session_id,
                turn_id=event.turn_id,
                payload=event.payload,
                hub_token=reg.token,
            )
            await reg.purpose.take_turn(addressed)
