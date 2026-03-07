"""
Canonical Turn Object (CTO).

The CTO is a pure value object — it carries data only. Profile-specific
attribute access is dispatched via __getattr__ → ProfileRegistry.resolve(),
which looks up the registered Profile by the (id, version) in content_profile.

No profile-specific code lives here. The CTO has no reference to the registry
or any profile object — it carries only the identifying data needed to perform
the lookup at access time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class CTO:
    """
    Canonical Turn Object — the hub-authoritative unit of sequential work.

    Created exclusively by the TTT hub via start_turn(). Nothing writes to
    canonical CTO state directly; all changes are proposed as Deltas and
    merged by the hub. Because CTO is frozen, each Delta merge produces a
    new CTO instance; the hub replaces the stored instance in _ctos.

    content_profile is a plain dict carrying the profile id and version:
        {"id": "conversation", "version": 1}
    This is fully serializable and loggable. No code or object references
    are stored on the CTO.

    Profile-specific attributes (e.g. cto.speaker_id, cto.text) are resolved
    at access time via __getattr__ → ProfileRegistry.resolve(). The registry
    is process-scoped; the CTO carries only the key needed to look up the
    right profile.

    Observations are purpose-owned namespaces written via Delta merge.
    Each Purpose writes to its own namespace (keyed by purpose_name);
    the hub enforces append-only semantics across all namespaces.
    Purposes may read any namespace but may only propose Deltas into
    their own.
    """

    turn_id: UUID
    session_id: UUID
    created_at_ms: int

    # Plain dict: {"id": str, "version": int}
    # Serializable and loggable as-is. No object references.
    content_profile: dict[str, Any]
    content: dict[str, Any]

    # purpose-owned namespaces: {purpose_name: [obs, ...]}
    # written via Delta merge; never mutated directly.
    observations: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    # TODO(delta-versioning): Add last_event_id: UUID | None = None
    # Set to the cto_created event_id at construction, updated to the
    # delta_merged event_id on each merge. Carried in CTOIndex so Purposes
    # can record based_on_event_id in their Delta proposals without calling
    # get_cto(). The hub validates based_on_event_id at merge time to detect
    # stale proposals — i.e. a Purpose reasoning about CTO state that has
    # since advanced. See Delta.based_on_event_id.

    def __getattr__(self, name: str) -> Any:
        """
        Delegate unknown attribute lookups to the registered Profile.

        Called by Python only when normal attribute resolution fails — i.e.
        name is not a dataclass field. Looks up the Profile via
        ProfileRegistry.resolve() using the (id, version) from content_profile.

        Raises AttributeError for names not registered as accessors on the
        profile, matching standard Python attribute access behavior.

        Note: uses object.__getattribute__ internally to avoid recursive calls
        during dataclass initialization, when fields may not yet be set.
        """
        # Import here to avoid circular import at module load time.
        from .profile import ProfileRegistry

        try:
            cp = object.__getattribute__(self, "content_profile")
            content = object.__getattribute__(self, "content")
        except AttributeError:
            raise AttributeError(f"{type(self).__name__!r} has no attribute {name!r}")
        try:
            return ProfileRegistry.resolve(cp["id"], cp["version"], name, content)
        except KeyError:
            raise AttributeError(f"{type(self).__name__!r} has no attribute {name!r}")

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize to a JSON-safe dict for persistence and transport.

        UUIDs are rendered as strings. content_profile serializes as-is —
        it is already a plain dict containing only id (str) and version (int).
        Observations are passed through as-is; callers are responsible for
        ensuring observation values are JSON-safe.
        """
        return {
            "turn_id": str(self.turn_id),
            "session_id": str(self.session_id),
            "created_at_ms": self.created_at_ms,
            "content_profile": self.content_profile,
            "content": self.content,
            "observations": self.observations,
        }

    def to_index(self) -> "CTOIndex":
        """
        Return a CTOIndex for this CTO — a lightweight routing reference.

        Carries only the fields needed for Purposes to make dispatch decisions
        without loading full content or observations. Purposes that need more
        call TTT.get_cto(turn_id).
        """
        return CTOIndex(
            turn_id=self.turn_id,
            session_id=self.session_id,
            content_profile=self.content_profile,
            created_at_ms=self.created_at_ms,
        )


@dataclass(frozen=True)
class CTOIndex:
    """
    Lightweight routing reference to a CTO.

    Carried in HubEvent payloads in place of the full CTO. Contains enough
    information for a Purpose to make a dispatch decision — profile type,
    identity, session — without the cost of serializing content or
    observations.

    Purposes that need full CTO state (content, observations, profile
    accessors) call TTT.get_cto(turn_id). ctoPersistP is the canonical
    example: it receives a CTOIndex, calls get_cto(), and persists the
    full canonical state.

    The hub is the authority for canonical CTO state. A CTOIndex is a
    pointer, not a snapshot — it does not carry a moment-in-time copy of
    observations or content.
    """

    turn_id: UUID
    session_id: UUID

    # {"id": str, "version": int} — sufficient for profile-based routing
    # decisions without loading full content.
    content_profile: dict[str, Any]
    created_at_ms: int

    # TODO(delta-versioning): Add last_event_id: UUID | None = None
    # Mirrors CTO.last_event_id. Carried here so Purposes can read the
    # current CTO version handle directly from the event payload and record
    # it as based_on_event_id in their Delta proposals — without needing
    # a separate get_cto() call just to get the version handle.

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize to a JSON-safe dict for event payload embedding.

        UUIDs are rendered as strings. content_profile serializes as-is.
        """
        return {
            "turn_id": str(self.turn_id),
            "session_id": str(self.session_id),
            "content_profile": self.content_profile,
            "created_at_ms": self.created_at_ms,
        }
