from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping
from uuid import UUID


@dataclass(frozen=True)
class CTO:
    """
    Canonical Turn Object.

    A CTO is the hub-authoritative, canonical work-item for one “turn-like” unit
    of processing. It is *profiled*: the hub stores the content under `content`,
    and the `content_profile` defines the required shape.

    Canonical example profile: "conversation"
      content = {"speaker": str, "text": str}

    NOTE: convenience properties (speaker/text) are derived and profile-scoped.
    """

    turn_id: UUID
    session_id: UUID
    created_at_ms: int

    content_profile: str
    content: dict[str, Any]

    # observations are purpose-owned namespaces: {purpose_name: [obs, obs, ...]}
    observations: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": str(self.turn_id),
            "session_id": str(self.session_id),
            "created_at_ms": self.created_at_ms,
            "content_profile": self.content_profile,
            "content": self.content,
            "observations": self.observations,
        }

    # ---- conversational conveniences ----

    @property
    def speaker(self) -> str | None:
        if self.content_profile != "conversation":
            return None
        v = self.content.get("speaker")
        return v if isinstance(v, str) else None

    @property
    def text(self) -> str | None:
        if self.content_profile != "conversation":
            return None
        v = self.content.get("text")
        return v if isinstance(v, str) else None


def validate_content_profile(content_profile: str, content: Mapping[str, Any]) -> None:
    """
    Minimal v0 validation. Tighten this later into a registry of profiles.

    Raises ValueError if the content does not match the profile contract.
    """
    if content_profile == "conversation":
        if not isinstance(content.get("speaker"), str):
            raise ValueError("conversation profile requires content['speaker']: str")
        if not isinstance(content.get("text"), str):
            raise ValueError("conversation profile requires content['text']: str")
        return

    # v0: allow unknown profiles but require dict-like content
    # later: require declared profile schemas in a registry
    if not isinstance(content, Mapping):
        raise ValueError("content must be a mapping")
