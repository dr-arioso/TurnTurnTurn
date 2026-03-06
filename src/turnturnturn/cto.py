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
    merged by the hub.

    content_profile is a plain dict carrying the profile id and version:
        {"id": "conversation", "version": 1}
    This is fully serializable and loggable. No code or object references
    are stored on the CTO.

    Profile-specific attributes (e.g. cto.speaker_id, cto.text) are resolved
    at access time via __getattr__ → ProfileRegistry.resolve(). The registry
    is process-scoped; the CTO carries only the key needed to look up the
    right profile.

    Observations are purpose-owned namespaces written via Delta merge.
    Each Purpose writes to its own key; the hub enforces append-only semantics.
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
