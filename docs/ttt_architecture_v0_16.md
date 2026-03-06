# TurnTurnTurn (TTT) — Architecture v0.16

## 0. Positioning

**TurnTurnTurn (TTT)** is a lightweight hub runtime for routing, enriching, and preserving provenance over sequential work items.

TTT is built around a single canonical object:

- **CTO** — Canonical Turn Object

TTT does **not** define domain semantics. It provides:

- authoritative CTO creation
- hub-mediated Delta merge
- typed HubEvents
- Purpose registration and dispatch
- replayable provenance through the event stream

The canonical example profile is **`conversation`**, but TTT is **profile-based**, not hard-coded to speaker/text semantics.

## 1. Core nouns

### TTT

The public hub runtime.

TTT is the authority for:

- creating CTOs
- merging Deltas
- emitting HubEvents
- maintaining Purpose registration
- enforcing routing and dispatch rules

### start_turn

The hub ingress method.

A caller invokes `ttt.start_turn(...)` with a session ID, content profile, and content dict. TTT validates the content against the profile, creates a CTO, emits `cto_created`, and dispatches interested Purposes.

### CTO

Canonical Turn Object.

A CTO is the authoritative, canonical work item created by TTT via `start_turn`.

Minimal shape:

- `turn_id`
- `session_id`
- `created_at_ms`
- `content_profile` — `{"id": str, "version": int}`
- `content`
- `observations`

The canonical example profile is:

- `content_profile = "conversation"`
- `content = {"speaker_id": str, "speaker_role": str, "speaker_label": str, "text": str}`

Convenience attributes (`speaker_id`, `speaker_role`, `speaker_label`, `text`) are **derived**, profile-scoped accessors.

### Purpose

A registered agenda-bearing actor in the TTT mesh.

A Purpose:

- has a semantic `name`
- has an instance `id`
- may later receive a nullable hub-assigned `token`
- subscribes to HubEvents
- may emit Deltas
- may, in future, invoke `start_turn` to submit new work items

A Purpose is **not** a per-turn work parcel.

### Delta

A purpose-proposed change.

A Delta does not mutate canonical state directly. TTT validates and merges Deltas into CTO observation state using deterministic, append-only rules.

### HubEvent

An authoritative event emitted by TTT.

HubEvents record lifecycle transitions and important actions. The event stream is the primary provenance surface and remains the replay and reconstruction substrate.

## 2. Core principles

### 2.1 TTT is authoritative

Only TTT may create CTOs or mutate canonical CTO state.

Purposes propose changes. TTT decides what becomes canonical.

### 2.2 Append-only by default

Canonical history is preserved.

TTT does not silently overwrite prior contributions. Merge behavior is deterministic and history-preserving.

### 2.3 Provenance is primarily in the event stream

The authoritative answer to “who contributed what, when” comes from HubEvents and replayable event history, not from stuffing provenance into every in-memory field.

### 2.4 Profiled core, not conversation-only core

TTT does not assume all CTOs are speaker/text turns.

Instead:

- CTO has `content_profile`
- CTO has authoritative `content`
- profiles define required content shape
- `conversation` is the canonical example profile

### 2.5 Purpose is an actor, not a packet

A Purpose is a registered participant with an agenda.

Per-turn dispatch, if modeled explicitly, is a runtime concern separate from the identity of the Purpose itself.

### 2.6 Routing and dependency are distinct

Routing answers: **who is interested?**

Dependency answers: **who is eligible now?**

Subscriptions and DAG constraints are related but not identical concerns.

## 3. Minimal lifecycle

### 3.1 Register Purpose

Calling code registers one or more Purposes with TTT.

Registration associates:

- `Purpose.name`
- `Purpose.id`
- nullable `token`
- subscriptions
- later: optional capabilities and DAG metadata

### 3.2 Start session

TTT creates or accepts session context.

### 3.3 Call start_turn

A caller invokes `start_turn` on TTT directly.

Example mental model:

```python
await ttt.start_turn(
    session_id=...,
    content_profile="conversation",
    content={
        "speaker": {"id": "usr_a3f9"},
        "text": "hello",
    },
)
```

### 3.4 TTT creates CTO

TTT validates the content against its content profile, creates the CTO, and emits:

- `cto_created`

### 3.5 Dispatch Purposes

TTT routes `cto_created` to subscribed and eligible Purposes.

### 3.6 Purposes emit Deltas

Purposes propose observation writes or other canonical contributions by emitting Deltas.

### 3.7 TTT merges Deltas

TTT validates and merges Deltas, then emits follow-up HubEvents such as:

- `delta_merged`
- `purpose_completed`

### 3.8 Repeat until quiescent

TTT continues routing and merge/dispatch cycles until no further eligible work remains.

## 4. Diagrams

### 4.1 System shape

```text
submitter / app / Purpose
          │
          ▼
    start_turn(session_id, content_profile, content, ...)
          │
          ▼
┌──────────────────────────────┐
│             TTT              │
│                              │
│  authoritative hub runtime   │
│  - validate content          │
│  - create CTO                │
│  - merge Deltas              │
│  - emit HubEvents            │
│  - enforce registry/routing  │
└──────────────────────────────┘
      │                │
      ▼                ▼
   subscriptions      DAG
   (interest)         (eligibility)
      │                │
      └──────┬─────────┘
             ▼
         Purposes
```

### 4.2 Creation boundary

```text
start_turn(...)  --invoked on-->  TTT
                                    │
                                    ├─ validate profile contract
                                    ├─ create CTO
                                    └─ emit cto_created { cto: ... }
```

### 4.3 Canonical event flow

```text
start_turn
   ↓
cto_created
   ↓
Purpose(s) take_turn(event)
   ↓
Delta(s) proposed
   ↓
delta_merged
   ↓
follow-on Purpose dispatch
```

## 5. Canonical example profile: `conversation`

TTT is profile-based, but `conversation` remains the canonical example because it is simple, legible, and central to Adjacency.

### 5.1 The profile system

A `Profile` is a self-contained schema object that owns validation, default application, and accessor resolution for one content shape. Profiles are registered in `ProfileRegistry` — a process-scoped class-level registry. The hub consults it at `start_turn()` time; `CTO.__getattr__` consults it at attribute access time.

The CTO carries only identifying data — no object references, no code:

```python
content_profile = {"id": "conversation", "version": 1}
```

This is fully serializable and loggable as-is. `CTO.__getattr__` dispatches to `ProfileRegistry.resolve(id, version, name, content)` for unknown attribute lookups. No profile-specific code lives in `CTO` or `hub.py`.

To add a new profile: construct a `Profile`, call `TTT.register_profile()`. No core module changes required.

### 5.2 Key convention

The conversation profile uses the **parent_child flat key convention** (max depth 2). Keys are grouped by parent prefix. Enforced when `strict_profiles=True` on the hub or `strict=True` on the profile; documented convention otherwise.

### 5.3 Content shape

```python
content_profile = "conversation"
content = {
    "speaker": {
        "id":    str,   # required — stable caller-defined identifier.
                        # no format enforced — model name, UUID, handle, etc.
                        # anchors ordinal assignment and provenance tracking.
        "role":  str,   # optional — semantic role in the session protocol.
                        # e.g. "subject", "interviewer", "user", "assistant".
                        # default: "speaker" (the parent key name).
        "label": str,   # optional — human-facing display name.
                        # e.g. "Stevie", "Human", "LLM", "Dr. Smith".
                        # default: "speaker_<n>" — 1-based ordinal of this
                        # speaker.id in the session's speaker registry.
                        # same speaker.id always resolves to the same
                        # ordinal within a session.
    },
    "text": str,        # required — the turn content. root-level field.
}
```

### 5.4 Accessor dispatch

Content is nested; CTO accessors are flat, following the parent_child
convention. `cto.speaker_id` resolves to `content["speaker"]["id"]` via
the path tuple declared in the profile's FieldSpec:

```python
cto.speaker_id     # → content["speaker"]["id"]
cto.speaker_role   # → content["speaker"]["role"]
cto.speaker_label  # → content["speaker"]["label"]
cto.text           # → content["text"]
```

Unknown attribute names raise `AttributeError` as normal. Accessors for unknown profiles raise `AttributeError` — there is no cross-profile fallback.

### 5.5 Computed accessors

Not supported in v0. All accessors are simple `content.get(name)` lookups. When computed accessors are needed (fields derived from multiple content keys), override `Profile.resolve()` on a subclass and register the subclass. No core changes required.

### 5.6 strict_profiles

`TTT.create(strict_profiles=True)` activates strict key validation on all profiles. Per-profile `strict=True` activates it for that profile regardless of the hub setting.

## 6. Event taxonomy (minimal v0.15)

### `cto_created`

A new CTO now exists and is canonical.

Payload includes:

- full CTO
- optional submitter attribution
- schema/version metadata

### `delta_merged`

TTT has accepted and merged a Delta into canonical state.

### `purpose_registered`

TTT has accepted a Purpose registration.

### `purpose_completed`

A Purpose has completed one unit of work associated with a CTO, if and when that concept remains useful.

This section should stay intentionally small.

## 7. Identification model

### Purpose identity

Each Purpose has:

- `name` — semantic kind, e.g. `"ca"`, `"embeddingizer"`, `"socratic"`
- `id` — concrete instance UUID
- `token` — nullable hub-assigned cryptographic token

Many Purposes may share the same `name`. `id` distinguishes instances.

### CTO identity

`turn_id` is the canonical CTO identity key.

### Event identity

Each HubEvent has its own `event_id`.

## 8. Module map

Source of truth lives in code.

Primary modules:

- `hub.py` — TTT runtime
- `protocols.py` — PurposeProtocol / TurnTakerProtocol
- `cto.py` — CTO; no profile-specific code
- `profile.py` — Profile, ProfileRegistry, FieldSpec; conversation profile built-in
- `events.py` — HubEvent and payload helpers
- `delta.py` — Delta
- `registry.py` — Purpose registration
- `dag.py` — eligibility model (stub)

This document is only the front door.

## 9. Non-goals for v0.15

TTT v0.15 does not yet attempt to fully specify:

- cross-process transport
- durable persistence layout
- auth policy beyond token seam
- domain semantics for observations
- final naming for `purpose_completed` event

## 10. Immediate open questions

- Decide whether `purpose_completed` survives or is replaced by a clearer event.
- Decide whether explicit per-dispatch runtime records need a named public abstraction.
- Decide how much DAG language belongs in the public doc versus in code-level docs.
- **Profile registry strict enforcement** — the `parent_child` key convention depth check in `Profile.validate(strict=True)` is a placeholder. Full enforcement (unknown key rejection by convention, not just by explicit field declaration) is deferred pending real usage driving the requirements.
- **Declarative profile system** — the intended future state is profiles-as-pure-data requiring no Python code, loadable from JSON or YAML. The design is sketched in `profile.py`'s module docstring and `profiles/conversation.py`'s TODO block. Key elements: nested `content` dict mirroring actual content shape; `field_interpolation` for structural token declaration; `accessor_rule` for CTO attribute name generation; `_ordinal_` magic token for session-scoped counters; `Profile.from_dict()` as the parser entry point. The seam is the three stable method signatures: `Profile.validate()`, `Profile.apply_defaults()`, `Profile.resolve()` — these must not change when the declarative system lands.

## 11. Migration notes from v0.14

This revision intentionally changes the public story:

- from **conversational turn processing** to **profile-based canonical work-item routing**
- from CTO fields `text` + `role` to CTO fields `content_profile` + `content`
- from `turn_received` to `cto_created`
- from `purpose_id` as overloaded type/instance language to `Purpose.name` + `Purpose.id`
- from `TurnSnargle` + `submit_snargle()` to direct `start_turn()` invocation on the hub
- from `content["speaker"]: str` to `content["speaker_id"]: str` (required) + `content["speaker_role"]: str` (optional) + `content["speaker_label"]: str` (optional) in the conversation profile
- from `CTO.speaker` convenience accessor to `CTO.speaker_id`, `CTO.speaker_role`, `CTO.speaker_label`
- from ad-hoc `validate_content_profile()` switch to `Profile` / `ProfileRegistry` — profile-specific code no longer lives in core modules
- `content_profile` on CTO changed from a string to a plain dict `{"id": ..., "version": ...}` — fully serializable, no object references
- hub `_speaker_registry` replaced by opaque `_session_contexts` — the hub no longer has any knowledge of speaker ordinals; the conversation profile manages that state in the session context dict it owns

It preserves:

- hub-authoritative merge semantics
- append-only observation history
- event-stream provenance as primary record
- switch-style routing plus DAG-gated eligibility
