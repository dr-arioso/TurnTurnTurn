# TurnTurnTurn (TTT) — Architecture v0.15

## 0. Positioning

**TurnTurnTurn (TTT)** is a hub runtime built around a single canonical object — the CTO — and the principle that nothing writes to canonical state directly. TTT was extracted from real human-AI interaction research infrastructure; the abstractions reflect actual usage rather than speculative design.

TTT is built around a single canonical object:

- **CTO** — Canonical Turn Object

TTT does **not** define domain semantics. It provides the machinery to adopt the semantics that are important to anyone who uses it.

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
- `content_profile`
- `content`
- `observations`

The canonical example profile is:

- `content_profile = "conversation"`
- `content = {"speaker": str, "text": str}`

Convenience attributes such as `speaker` and `text` are **derived**, profile-scoped accessors.

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
    content={"speaker": "user", "text": "hello"},
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

Required content shape:

```python
content_profile = "conversation"
content = {
    "speaker": "...",
    "text": "...",
}
```

Convenience accessors:

- `CTO.speaker`
- `CTO.text`

These are derived from `content` and valid only when `content_profile == "conversation"`.

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
- `cto.py` — CTO and content-profile validation
- `events.py` — HubEvent and payload helpers
- `delta.py` — Delta
- `registry.py` — Purpose registration
- `dag.py` — eligibility model

This document is only the front door.

## 9. Non-goals for v0.15

TTT v0.15 does not yet attempt to fully specify:

- cross-process transport
- durable persistence layout
- auth policy beyond token seam
- profile registry mechanics beyond minimal validation
- domain semantics for observations
- final naming for `purpose_completed` event

## 10. Immediate open questions

- Decide whether `purpose_completed` survives or is replaced by a clearer event.
- Decide whether explicit per-dispatch runtime records need a named public abstraction.
- Decide how much DAG language belongs in the public doc versus in code-level docs.

## 11. Migration notes from v0.14

This revision intentionally changes the public story:

- from **conversational turn processing** to **profile-based canonical work-item routing**
- from CTO fields `text` + `role` to CTO fields `content_profile` + `content`
- from `turn_received` to `cto_created`
- from `purpose_id` as overloaded type/instance language to `Purpose.name` + `Purpose.id`
- from `TurnSnargle` + `submit_snargle()` to direct `start_turn()` invocation on the hub

It preserves:

- hub-authoritative merge semantics
- append-only observation history
- event-stream provenance as primary record
- switch-style routing plus DAG-gated eligibility
