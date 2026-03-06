"""
Conversation profile (v1) for TurnTurnTurn.

The conversation profile models a single turn in a human/AI or multi-party
interaction. It is the canonical example profile shipped with TTT.

## Content shape

    content = {
        "speaker": {
            "id":    str,   # required — stable identity anchor
            "role":  str,   # optional — semantic role in the session
            "label": str,   # optional — human-readable display name
        },
        "text": str,        # required — the turn content
    }

The three speaker fields follow the parent_child convention: "speaker" is
the parent entity; "id", "role", and "label" are its child attributes. CTO
accessors are named by the same convention: cto.speaker_id, cto.speaker_role,
cto.speaker_label, cto.text.

This pattern — id for stable identity, role for semantic classification,
label for human-readable display — is the recommended model for any content
entity in a future profile.

`text` has no parent prefix because it is not an attribute of an entity;
it is the content of the turn itself.

## Fields

### speaker.id (required)

Stable caller-defined identifier for this speaker. No format enforced —
model names ("claude-sonnet-4-6"), opaque handles ("usr_a3f9"), UUIDs, or
any other string the calling system uses. Required because it anchors
ordinal assignment and provenance tracking across the session.

### speaker.role (optional)

Semantic role of the speaker in the session protocol. Describes the
*function* of the participant, not who they are.

Examples: "subject", "interviewer", "user", "assistant", "moderator"

Default: "speaker" (the parent key name — a neutral fallback).

### speaker.label (optional)

Human-facing display name for this speaker. Used by persistence layers,
transcripts, and any consumer that needs to render output for human readers.

Examples: "Stevie", "Human", "LLM", "Dr. Smith", "Participant 1"

Default: "speaker_<n>" where n is the 1-based ordinal position of this
speaker.id in the session's speaker registry. The same speaker.id always
resolves to the same ordinal within a session. Ordinal state is maintained
in the session context under the key "conversation.speakers" — the hub
passes this through opaquely and the profile owns its contents entirely.

### text (required)

The content of the turn. Root-level field — no parent entity.

## Strict mode

When strict=True (via hub strict_profiles or profile-level strict flag),
unknown keys are rejected. The parent_child convention depth check is a
placeholder pending real usage driving the full enforcement requirements.

## Example

```python
await ttt.start_turn(
    session_id=session_id,
    content_profile="conversation",
    content={
        "speaker": {
            "id":    "claude-sonnet-4-6",
            "role":  "assistant",   # optional
            "label": "Claude",      # optional
        },
        "text": "Hello, how can I help?",
    },
)
```

Minimal (hub fills speaker.role and speaker.label from defaults):

```python
await ttt.start_turn(
    session_id=session_id,
    content_profile="conversation",
    content={
        "speaker": {"id": "claude-sonnet-4-6"},
        "text": "Hello, how can I help?",
    },
)
```

## TODO(declarative-profiles)

The build() function below is the current implementation form. The intended
future replacement is a declarative dict passed to Profile.from_dict():

    Profile.from_dict({
        "profile_id": "conversation",
        "field_interpolation": {
            "<level_1_key>": {"<level_2_key>": None}
        },
        "content": {
            "speaker": {
                "id":    {"type": "str", "field_attributes": {"required": True,  "autogenerate": False}},
                "label": {"type": "str", "field_attributes": {"required": False, "autogenerate": "<level_1_key>_<_ordinal_>"}},
                "role":  {"type": "str", "field_attributes": {"required": False, "autogenerate": "<level_1_key>"}},
            },
            "text": {"type": "str", "field_attributes": {"required": True, "autogenerate": False}},
        },
        "accessor_rule": {
            "name": "key_concatenation_rule",
            "rule": "<level_1_key>_<level_2_key>",
        },
        "_ordinal_": {"match_on": "speaker.id"},
    })

When Profile.from_dict() is implemented, this module's build() function
becomes a thin wrapper or is replaced entirely. The profile's behavior —
validation, defaulting, accessor resolution — is unchanged.
"""

from __future__ import annotations

from typing import Any

from ..profile import FieldSpec, Profile


def build() -> Profile:
    """
    Build and return the conversation Profile (v1).

    Called by ProfileRegistry.load_defaults(). Returns a fresh Profile
    instance — safe to call multiple times.

    TODO(declarative-profiles): Replace with Profile.from_dict() call
    once the declarative profile system is implemented. See module docstring
    for the target declaration format.
    """
    return Profile(
        profile_id="conversation",
        version=1,
        strict=False,
        fields={
            "speaker_id": FieldSpec(
                name="speaker_id",
                path=("speaker", "id"),
                required=True,
                expected_type=str,
            ),
            "speaker_role": FieldSpec(
                name="speaker_role",
                path=("speaker", "role"),
                required=False,
                expected_type=str,
                default_factory=lambda content, ctx: "speaker",
            ),
            "speaker_label": FieldSpec(
                name="speaker_label",
                path=("speaker", "label"),
                required=False,
                expected_type=str,
                default_factory=_speaker_label_default,
            ),
            "text": FieldSpec(
                name="text",
                path=("text",),
                required=True,
                expected_type=str,
            ),
        },
    )


def _speaker_label_default(
    content: dict[str, Any],
    session_context: dict[str, Any],
) -> str:
    """
    Resolve or assign a stable ordinal label for this speaker.

    Reads and writes session_context["conversation.speakers"] to maintain
    a per-session {speaker_id: ordinal} registry. The same speaker.id
    always returns the same label within a session.

    TODO(declarative-profiles): Replaced by the <_ordinal_> magic token
    with match_on="speaker.id" in the declarative format.
    """
    speaker_id = content.get("speaker", {}).get("id", "")
    speakers = session_context.setdefault("conversation.speakers", {})
    if speaker_id not in speakers:
        speakers[speaker_id] = len(speakers) + 1
    return f"speaker_{speakers[speaker_id]}"
