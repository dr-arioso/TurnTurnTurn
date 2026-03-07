# TurnTurnTurn (TTT) — Architecture v0.17

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

The public hub runtime. Instantiate via `TTT.create()`.

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

A CTO is the authoritative, canonical work item created by TTT via `start_turn`. It is frozen — each Delta merge produces a new CTO instance; the hub replaces the stored instance.

Minimal shape:

- `turn_id`
- `session_id`
- `created_at_ms`
- `content_profile` — `{"id": str, "version": int}`
- `content`
- `observations` — purpose-owned namespaces: `{purpose_name: [obs, ...]}`

> **TODO(delta-versioning):** `last_event_id` will be added — the `event_id` of the most recent `cto_created` or `delta_merged` event. Carried in `CTOIndex` so Purposes can record `based_on_event_id` in Delta proposals without a separate `get_cto()` call. See §10.

The canonical example profile is:

- `content_profile = {"id": "conversation", "version": 1}`
- `content = {"speaker": {"id": str, "role": str, "label": str}, "text": str}`

Profile-scoped accessors (`speaker_id`, `speaker_role`, `speaker_label`, `text`) are **derived** — resolved at access time by walking `FieldSpec.path` into the nested content dict. No flat key assumptions.

### CTOIndex

A lightweight routing reference to a CTO, carried in HubEvent payloads.

Contains enough for a Purpose to make a dispatch decision — profile type, identity, session — without the cost of serializing content or observations. Purposes that need full CTO state call `TTT.get_cto(turn_id)`.

`CTOIndex` is a pointer, not a snapshot. It does not carry a moment-in-time copy of observations.

### Purpose

A registered agenda-bearing actor in the TTT mesh.

A Purpose:

- has a semantic `name` (doubles as its observation namespace key)
- has an instance `id`
- receives a hub-assigned `token` at registration time — non-nullable after registration
- subscribes to HubEvents
- proposes Deltas into its own namespace
- may read observations from any namespace
- may, in future, invoke `start_turn` to submit new work items

A Purpose is **not** a per-turn work parcel.

**`BasePurpose`** is the recommended implementation base. It enforces that `take_turn()` rejects events whose `hub_token` does not match the assigned token, closing the point-to-point bypass. Subclasses implement `_handle_event()` and must not override `take_turn()`.

### Delta

A purpose-proposed change.

A Delta does not mutate canonical state directly. TTT validates and merges Deltas into CTO observation state using deterministic, append-only rules. All patch values must be lists.

> **TODO(delta-versioning):** `based_on_event_id` will be added — the `event_id` of the CTO state the proposing Purpose was reading when it constructed the Delta. Read from `CTOIndex.last_event_id` in the triggering event payload. The hub will compare against `CTO.last_event_id` at merge time; mismatch indicates stale reasoning. See §10.

### HubEvent

An authoritative event emitted by TTT.

HubEvents record lifecycle transitions. The event stream is the primary provenance surface and remains the replay and reconstruction substrate.

Payloads carry a **`CTOIndex`** (not a full CTO snapshot) and provenance metadata. Purposes that need full CTO state call `TTT.get_cto(turn_id)`.

Each event envelope is **per-recipient** — the hub stamps `hub_token` with the receiving Purpose's assigned token before dispatch. This allows `BasePurpose.take_turn()` to validate the source and reject point-to-point calls from other Purposes.

## 2. Core principles

### 2.1 TTT is authoritative

Only TTT may create CTOs or mutate canonical CTO state.

Purposes propose changes. TTT decides what becomes canonical.

### 2.2 Append-only by default

Canonical history is preserved.

TTT does not silently overwrite prior contributions. Merge behavior is deterministic and history-preserving. All Delta patch values must be lists; the hub extends, never replaces.

### 2.3 Provenance is primarily in the event stream

The authoritative answer to "who contributed what, when" comes from HubEvents and replayable event history, not from stuffing provenance into every in-memory field.

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

### 2.7 Hub dispatch is the only valid dispatch path

Purposes must not call `take_turn()` on each other directly. The only valid source of a HubEvent is the hub. `BasePurpose.take_turn()` enforces this via hub token validation — point-to-point calls will not carry a valid token and will raise `UnauthorizedDispatchError`.

Purposes that want to trigger work on other Purposes propose a Delta. The hub decides what happens next.

### 2.8 Events carry references, not snapshots

HubEvent payloads carry a `CTOIndex` — a lightweight routing reference — not a full CTO snapshot. This keeps the event bus lean regardless of observation accumulation. Purposes that need full state call `TTT.get_cto(turn_id)`. `ctoPersistP` is the canonical consumer of this pattern.

## 3. Minimal lifecycle

### 3.1 Register Purpose

Calling code registers one or more Purposes with TTT via `TTT.register_purpose()`.

Registration:

- associates `Purpose.name`, `Purpose.id`, and `subscriptions`
- generates a cryptographic token and assigns it to the Purpose via `BasePurpose._assign_token()`
- stores a `PurposeRegistration` record keyed by `purpose.id`

After registration the Purpose's token is non-nullable and the Purpose is ready to receive events.

### 3.2 Start session

TTT creates or accepts session context.

### 3.3 Call start_turn

A caller invokes `start_turn` on TTT directly.

Example:

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

TTT validates the content against its content profile, applies defaults, creates the CTO, stores it in `_ctos`, and emits:

- `cto_created`

### 3.5 Dispatch Purposes

TTT routes `cto_created` to registered Purposes. Each Purpose receives a per-recipient envelope with its own `hub_token` stamped in.

### 3.6 Purposes propose Deltas

Purposes call `TTT.get_cto(turn_id)` if they need full content or observations, then propose observation writes by submitting Deltas to the hub via `TTT.merge_delta()`.

### 3.7 TTT merges Deltas

TTT validates and merges Deltas (append-only, namespace-scoped), constructs a new CTO instance with updated observations, and emits:

- `delta_merged`

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
                                    └─ emit cto_created { cto_index: ..., submitted_by: ... }
```

### 4.3 Canonical event flow

```text
start_turn
   ↓
cto_created  { cto_index, submitted_by }
   ↓
Purpose(s) _handle_event(event)   ← validated by take_turn() via hub_token
   ↓
TTT.merge_delta(delta) proposed
   ↓
delta_merged  { delta, cto_index }
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

To add a new profile: construct a `Profile` with `FieldSpec` declarations, call `TTT.register_profile()`. No core module changes required.

### 5.2 Key convention

The conversation profile uses the **parent_child flat accessor convention** (max depth 2). CTO accessor names are derived from the content path: `speaker.id` → `speaker_id`. The actual content dict is nested; `FieldSpec.path` is the source of truth for traversal. Enforced when `strict_profiles=True` on the hub or `strict=True` on the profile; documented convention otherwise.

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
convention. `cto.speaker_id` resolves to `content["speaker"]["id"]` by
walking the path tuple `("speaker", "id")` declared in the profile's `FieldSpec`:

```python
cto.speaker_id     # → content["speaker"]["id"]
cto.speaker_role   # → content["speaker"]["role"]
cto.speaker_label  # → content["speaker"]["label"]
cto.text           # → content["text"]
```

Unknown attribute names raise `AttributeError` as normal. Accessors for unknown profiles raise `AttributeError` — there is no cross-profile fallback.

### 5.5 Computed accessors

Not supported in v0. All accessors walk `FieldSpec.path` into the nested content dict. When computed accessors are needed (fields derived from multiple content keys), override `Profile.resolve()` on a subclass and register the subclass. No core changes required.

### 5.6 strict_profiles

`TTT.create(strict_profiles=True)` activates strict key validation on all profiles. Per-profile `strict=True` activates it for that profile regardless of the hub setting.

## 6. Event taxonomy (v0.17)

### `cto_created`

A new CTO now exists and is canonical.

Payload includes:

- `cto_index` — `CTOIndex` dict (turn_id, session_id, content_profile, created_at_ms)
- optional submitter attribution (`submitted_by_label`, `submitted_by_purpose_id`, `submitted_by_purpose_name`)
- `_schema` / `_v` metadata for deserializer dispatch

### `delta_merged`

TTT has accepted and merged a Delta into canonical state.

Payload includes:

- `delta` — full serialized Delta (provenance record)
- `cto_index` — `CTOIndex` dict reflecting the post-merge CTO state

### `purpose_registered`

TTT has accepted a Purpose registration. Not yet emitted in v0.

### `purpose_completed`

Open question — see §10.

This section should stay intentionally small.

## 7. Identification model

### Purpose identity

Each Purpose has:

- `name` — semantic kind, e.g. `"ca"`, `"embeddingizer"`, `"socratic"`
- `id` — concrete instance UUID
- `token` — hub-assigned cryptographic token, assigned at registration, non-nullable after registration

Many Purposes may share the same `name`. `id` distinguishes instances. `token` authenticates hub dispatch.

### CTO identity

`turn_id` is the canonical CTO identity key.

### Event identity

Each HubEvent has its own `event_id`.

> **TODO(delta-versioning):** `CTO.last_event_id` will track the `event_id` of the most recent event that produced or updated this CTO. See §10.

### CTOIndex

`CTOIndex` is the lightweight event-payload form of CTO identity. Carries `turn_id`, `session_id`, `content_profile`, and `created_at_ms`. Used by Purposes for routing decisions without loading full state.

## 8. Module map

Source of truth lives in code.

Primary modules:

- `hub.py` — TTT runtime
- `base_purpose.py` — BasePurpose abstract base class; hub token validation; `_handle_event()` override point
- `protocols.py` — PurposeProtocol / TurnTakerProtocol
- `cto.py` — CTO and CTOIndex; no profile-specific code
- `profile.py` — Profile, ProfileRegistry, FieldSpec, path-walking helpers; conversation profile built-in
- `events.py` — HubEvent and payload helpers
- `delta.py` — Delta
- `registry.py` — PurposeRegistration
- `errors.py` — TTTError, UnauthorizedDispatchError, UnboundPurposeError
- `dag.py` — eligibility model (stub)

This document is only the front door.

## 9. Non-goals for v0.17

TTT v0.17 does not yet attempt to fully specify:

- cross-process transport
- durable persistence layout
- auth policy beyond hub token seam
- domain semantics for observations
- final naming for `purpose_completed` event
- DAG eligibility layer (stub only)
- delta versioning / stale-proposal handling policy

## 10. Immediate open questions

- **Delta versioning** — `CTO.last_event_id` and `Delta.based_on_event_id` are designed and TODOs placed in code, but not yet implemented. When implemented: the hub compares `delta.based_on_event_id` against `cto.last_event_id` at merge time. Mismatch means the proposing Purpose was reasoning about stale state. Handling policy (reject, warn, pass to resolver Purpose) is deferred until Adjacency integration drives the requirements.
- Decide whether `purpose_completed` survives or is replaced by a clearer event.
- Decide whether explicit per-dispatch runtime records need a named public abstraction.
- Decide how much DAG language belongs in the public doc versus in code-level docs.
- **Profile registry strict enforcement** — the `parent_child` key convention depth check in `Profile.validate(strict=True)` is a placeholder. Full enforcement (unknown key rejection by convention, not just by explicit field declaration) is deferred pending real usage driving the requirements.
- **Declarative profile system** — the intended future state is profiles-as-pure-data requiring no Python code, loadable from JSON or YAML. The design is sketched in `profile.py`'s module docstring and `profiles/conversation.py`'s TODO block. The seam is the three stable method signatures: `Profile.validate()`, `Profile.apply_defaults()`, `Profile.resolve()` — these must not change when the declarative system lands.

## 11. Migration notes

### v0.17 (this revision)

- `BasePurpose` added — abstract base class for all Purposes. Subclasses implement `_handle_event()` and must not override `take_turn()`.
- Hub token is now **assigned at registration**, not later. Non-nullable after `TTT.register_purpose()`. `BasePurpose._assign_token()` is called by the hub exclusively.
- `take_turn()` now validates `hub_token` on every call. Unregistered Purposes raise `UnboundPurposeError`; token mismatch raises `UnauthorizedDispatchError`. This closes the point-to-point bypass.
- HubEvent payloads now carry **`CTOIndex`** instead of a full CTO snapshot. `cto_created` and `delta_merged` payloads both use `cto_index` key. Full CTO state is retrieved via `TTT.get_cto(turn_id)`.
- `CTOIndex` added to `cto.py` and public API — lightweight routing reference carrying `turn_id`, `session_id`, `content_profile`, `created_at_ms`.
- `CTO.to_index()` added — factory method producing a `CTOIndex` from a CTO.
- `TTT.get_cto(turn_id)` added — read path for Purposes needing full CTO state.
- `TTT._ctos` added — canonical CTO store on the hub, keyed by `turn_id`.
- `_multicast()` now constructs per-recipient `HubEvent` envelopes, stamping `hub_token` for each registered Purpose.
- `errors.py` filled in — `TTTError`, `UnauthorizedDispatchError`, `UnboundPurposeError`.
- Profile `validate()`, `apply_defaults()`, and `resolve()` now walk `FieldSpec.path` into the nested content dict. The flat accessor name is purely a CTO handle; it never indexes into content directly.
- Path-walking helpers `_get_by_path`, `_set_by_path`, `_deep_copy_content` added to `profile.py`.
- `merge_delta()` added to TTT — validates Delta, enforces append-only patch shape, constructs updated CTO, emits `delta_merged`.
- `payload_delta_merged()` added to `events.py`.

### v0.16 (from v0.15)

- from **conversational turn processing** to **profile-based canonical work-item routing**
- from CTO fields `text` + `role` to CTO fields `content_profile` + `content`
- from `turn_received` to `cto_created`
- from `purpose_id` as overloaded type/instance language to `Purpose.name` + `Purpose.id`
- from `TurnSnargle` + `submit_snargle()` to direct `start_turn()` invocation on the hub
- from `content["speaker"]: str` to nested `content["speaker"]["id"]` (required), `content["speaker"]["role"]` (optional), `content["speaker"]["label"]` (optional)
- from `CTO.speaker` accessor to `CTO.speaker_id`, `CTO.speaker_role`, `CTO.speaker_label`
- from ad-hoc `validate_content_profile()` switch to `Profile` / `ProfileRegistry`
- `content_profile` on CTO changed from string to plain dict `{"id": ..., "version": ...}`
- hub `_speaker_registry` replaced by opaque `_session_contexts`

It preserves:

- hub-authoritative merge semantics
- append-only observation history
- event-stream provenance as primary record
- switch-style routing plus DAG-gated eligibility
