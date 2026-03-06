"""TTT hub runtime — authoritative CTO creation, Delta merge, and event emission."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from .cto import CTO
from .events import HubEvent, HubEventType, payload_cto_created
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

    Profile lookup delegates to the process-scoped ProfileRegistry class.
    The hub calls ProfileRegistry.load_defaults() at creation time to ensure
    built-in profiles are available. Custom profiles are registered via
    TTT.register_profile(), which delegates to ProfileRegistry.register().

    The hub maintains an opaque per-session context dict for each active
    session and passes it to Profile.apply_defaults() as a mutable dict.
    The hub never inspects context contents — profiles own them entirely.
    This allows profiles to maintain session-scoped state (e.g. speaker
    ordinals for label defaults) without leaking domain knowledge into the hub.

    Args:
        registrations: Purpose registry, keyed by purpose.id.
        strict_profiles: If True, all profiles enforce strict key validation
            at start_turn() time, regardless of per-profile strict flag.
        _session_contexts: Internal opaque per-session context store.
            {session_id: dict}. Contents are profile-owned; hub passes
            through without inspection. Not a constructor argument.
    """

    registrations: dict[UUID, PurposeRegistration]
    strict_profiles: bool = False
    _session_contexts: dict[UUID, dict[str, Any]] = field(
        default_factory=dict, init=False, repr=False
    )

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
        Register a Purpose with the hub.

        After registration, the Purpose will receive HubEvents via take_turn()
        on each multicast. Re-registering an existing purpose.id overwrites the
        prior registration.

        Args:
            purpose: The Purpose instance to register. Must satisfy PurposeProtocol.
            subscriptions: Event filter hints for future subscription matching.
                Currently unused in v0 — all registered Purposes receive all
                events. Will be enforced once the DAG/subscription layer lands.
        """
        # v0: in-memory registry only. Later: emit PURPOSE_REGISTERED, persist, auth.
        subs = subscriptions or []
        self.registrations[purpose.id] = PurposeRegistration(
            purpose=purpose,
            token=purpose.token,
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

        event = HubEvent(
            event_type=HubEventType.CTO_CREATED,
            event_id=uuid4(),
            created_at_ms=now_ms(),
            session_id=cto.session_id,
            turn_id=cto.turn_id,
            payload=payload_cto_created(
                cto_dict=cto.to_dict(),
                submitted_by_label=submitted_by_label,
            ),
        )

        await self._multicast(event)
        # v0: no DAG yet; dispatch is "all registered purposes for this event"
        return cto.turn_id

    async def _multicast(self, event: HubEvent) -> None:
        """
        Broadcast a HubEvent to all registered Purposes.

        v0: naive broadcast — every registered Purpose receives every event.

        Later:
          - subscription matching by event_type (+ filters)
          - DAG eligibility gating
          - persistence via a persist Purpose
        """
        for reg in self.registrations.values():
            await reg.purpose.take_turn(event)
