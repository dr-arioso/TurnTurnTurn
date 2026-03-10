# TurnTurnTurn (TTT) — Architecture v0.20

## 0. Positioning

**TurnTurnTurn (TTT)** is a provenance-first hub for conversational turn
processing. It coordinates registered Purposes, maintains canonical CTO state,
and records authoritative hub transitions as a replayable event stream.

TTT is built around a single canonical object:

- **CTO** — Canonical Turn Object

TTT does **not** define domain semantics. It provides:

- authoritative CTO creation
- hub-mediated Delta merge
- typed event envelopes
- Purpose registration and authenticated routing
- replayable provenance through the event stream
- mandatory persistence at hub startup

The canonical example profile is **`conversation`**, but TTT is
**profile-based**, not hard-coded to speaker/text semantics.

## 0.1 Invariants

These are the hard commitments. Everything else in this document is mechanism
around them.

- Only TTT may create CTOs.
- Only TTT may make canonical state changes.
- Purposes propose; they do not commit.
- Hub-authored events are authoritative records of hub-made transitions.
- CTO carries profile identity, not profile behavior.
- Canonical observation history is append-only.
- Event payloads carry references, not full state snapshots.
- `based_on_event_id` is provenance only — not stale-write detection.
- Bootstrap methods (`start_turn`, `start_purpose`) stand outside the event model by necessity, not by exception.
- Every hub-authored event reaches persistence before any domain Purpose receives it.
- `session_started` and `session_completed` are persistence-only lifecycle events.
- The hub will not start without a registered persistence backend.

## 1. Core nouns

### TTT

The public hub runtime. Start via `TTT.start(persistence_purpose)`.

TTT is the authority for:

- creating CTOs
- merging Deltas
- emitting hub-authored events
- maintaining Purpose registration
- enforcing routing and dispatch rules
- coordinating persistence writes

The **librarian** (`ttt.librarian`) is the query interface for CTO state.
It is the read path, not the authority path.

### start_turn

One of two bootstrap methods on the hub. The other is `start_purpose()`.

`start_turn()` is the ingress point for CTO creation — by external callers,
by application code, and by Purposes that generate new CTOs as part of their
own processing. It is a named method rather than an event because it is the
precondition for the event model: no `CTOIndex` exists until a CTO is
created, so no well-formed event can represent this act.

A caller invokes `ttt.start_turn(content_profile, content, hub_token)` with a
content profile identifier, content dict, and a hub-issued token identifying
the submitting Purpose. `session_id` is an optional keyword argument; the hub
mints a UUID if absent. TTT looks up the profile in `ProfileRegistry`,
validates the content, applies defaults, creates a CTO, emits `cto_started`,
and dispatches interested Purposes.

Every `start_turn()` caller must hold a valid hub-issued token — obtained by
registering a Purpose via `start_purpose()`. There is no anonymous ingress.
`submitted_by_label` is retired; attribution is always via Purpose identity.

### CTO

Canonical Turn Object.

A CTO is the authoritative work item created by TTT via `start_turn()`. It is
frozen — each accepted Delta merge produces a new CTO instance; the hub
replaces the stored instance.

Minimal shape:

- `turn_id`
- `session_id`
- `created_at_ms`
- `content_profile` — `{"id": str, "version": int}`
- `content`
- `observations` — purpose-owned namespaces: `{purpose_name: [obs, ...]}`
- `last_event_id` — the `event_id` of the most recent `cto_started` or
  `delta_merged` event that produced this CTO instance. Set at construction;
  updated on every merge. Carried in `CTOIndex` so Purposes can record it as
  `based_on_event_id` without a separate librarian call.

The canonical example profile is:

- `content_profile = {"id": "conversation", "version": 1}`
- `content = {"speaker": {"id": str, "role": str, "label": str}, "text": str}`

Profile-scoped accessors (`speaker_id`, `speaker_role`, `speaker_label`,
`text`) are **derived** — resolved at access time by walking `FieldSpec.path`
into the nested content dict. No flat-key assumptions.

### Observations and namespaces

Observations accumulate in per-Purpose namespaces inside the CTO.

Each Purpose writes exclusively to its own namespace (keyed by
`purpose_name`). The hub enforces this at merge time: a Delta proposing
writes outside the submitting Purpose's namespace is rejected.

TTT currently enforces purpose-owned contribution namespaces. Cross-purpose
observations are deferred pending a concrete use case. The architecture does
not preclude a future shared or reconciled workspace, but no such namespace is
currently normative.

### CTOIndex

A lightweight routing reference to a CTO, carried in hub-authored event
payloads.

It contains enough information for a Purpose to make a dispatch decision —
profile type, identity, session, and provenance handle — without serializing
full content or observations. Purposes that need full CTO state call
`ttt.librarian.get_cto(turn_id)`.

`CTOIndex` carries `last_event_id`, mirroring `CTO.last_event_id` at the
moment the index was produced. Purposes use this as `based_on_event_id` when
constructing Delta proposals — it records which canonical CTO state the
Purpose was reading when it decided to propose the change.

`CTOIndex` is a pointer, not a snapshot.

### Purpose

A registered agenda-bearing actor in the TTT mesh.

A Purpose:

- has a semantic `name` (also its observation namespace key)
- has an instance `id`
- receives a hub-assigned `token` at registration — non-nullable after `start_purpose()`
- subscribes to hub-authored events by profile and event type
- proposes Deltas into its own namespace
- may read observations from any namespace
- may invoke `start_turn()` to submit new CTOs into the mesh
- communicates with the hub exclusively via `hub.take_turn(event)` after bootstrap

A Purpose is **not** a per-turn work parcel.

**`BasePurpose`** is the recommended implementation base. It enforces that
`take_turn()` rejects events whose `hub_token` does not match the assigned
token, closing the point-to-point bypass. Subclasses implement
`_handle_event()` and must not override `take_turn()`.

### Delta

A purpose-proposed change.

A Delta does not mutate canonical state directly. TTT validates and merges
Deltas into CTO observation state using deterministic, append-only rules. All
patch values must be lists.

`based_on_event_id` is a provenance field — the `last_event_id` of the CTO
state the proposing Purpose was reading when it constructed the Delta. Read
from `CTOIndex.last_event_id` in the triggering event payload; no extra
librarian call required. Recorded in the persisted Delta for causal
reconstruction and replay. `None` if the proposing Purpose did not record it.

`based_on_event_id` is **not** a conflict-detection mechanism. Because all
observations are append-only and namespace-scoped, there are no destructive
writes to conflict. It answers: *what canonical state was this Purpose
reasoning from?*

### Event policy

The hub maintains an internal event policy registry mapping Purpose-authored
event types to optional built-in handlers.

Events without handlers are still accepted and routed through the hub substrate
but do not trigger built-in hub behavior.

### Hub-authored events

Hub-authored events are authoritative records emitted by TTT.

They record lifecycle transitions that the hub has made true. The event stream
is the primary provenance surface and remains the replay and reconstruction
substrate.

Payloads carry a **`CTOIndex`** (not a full CTO snapshot) plus event-specific
metadata. Purposes that need full CTO state call `ttt.librarian.get_cto()`.

Each event envelope is **per-recipient** — the hub stamps `hub_token` with the
receiving Purpose's assigned token before dispatch. This allows
`BasePurpose.take_turn()` to validate the source and reject point-to-point
calls from other Purposes.

### Librarian

`ttt.librarian` is the query interface for CTO state.

It is a named object on the hub rather than a bare method because its
responsibilities will grow: point lookups today, session readback and replay
queries later. The hub is an authority and router; the librarian is the read
path.

Current interface:

- `ttt.librarian.get_cto(turn_id)` — returns the current canonical CTO, or
  `None` if unknown

Planned interface (deferred):

- session readback
- replay-oriented retrieval
- persistence-backed historical queries

### Persistence and Archivist

Persistence is mandatory at hub startup.

The hub requires a persistence backend when `TTT.start(...)` is called. That
backend is bootstrapped before any domain Purpose registration or turn
processing.

There are currently two related persistence stories:

- **`InMemoryPersistencePurpose`** — the lightweight in-core persistence sink,
  useful for tests and development; not durable
- **`Archivist`** — the durable persistence layer, backed by one or more
  backends such as JSONL or session-document storage

The architectural commitments are:

- persistence starts before the domain mesh
- `session_started` is written first
- every later hub-authored event reaches persistence before domain delivery
- `session_completed` is written last

Domain Purposes do not receive `session_started` or `session_completed`.
Those are persistence-only lifecycle records.

## 2. Core principles

### 2.1 TTT is authoritative

Only TTT may create CTOs or mutate canonical CTO state.

Purposes propose changes. TTT decides what becomes canonical.

### 2.2 Append-only by default

Canonical history is preserved.

TTT does not silently overwrite prior contributions. Merge behavior is
deterministic and history-preserving. All Delta patch values must be lists;
the hub extends, never replaces.

### 2.3 Provenance lives primarily in the event stream

The authoritative answer to “who contributed what, when” comes from the event
stream and replayable event history, not from stuffing provenance into every
in-memory field.

### 2.4 Profiled core, not conversation-only core

TTT does not assume all CTOs are speaker/text turns.

Instead:

- CTO has `content_profile`
- CTO has authoritative `content`
- profiles define required content shape
- `conversation` is the canonical example profile

### 2.5 Purpose is an actor, not a packet

A Purpose is a registered participant with an agenda.

Per-turn dispatch, if modeled explicitly, is a runtime concern separate from
the identity of the Purpose itself.

### 2.6 Routing and dependency are distinct

Routing answers: **who is interested?**

Dependency answers: **who is eligible now?**

Subscriptions and DAG constraints are related but not identical concerns.
Profile match is the first filter: a Purpose registered for `"conversation"`
CTOs does not receive dispatch for a `"document_review"` CTO, regardless of
subscriptions or future eligibility machinery.

Current dispatch order is:

1. **Profile match** — does this Purpose handle this CTO profile?
2. **Subscription match** — has this Purpose subscribed to this event type?
3. **Built-in routing rules** — does the hub send this event to domain Purposes at all?

Future DAG eligibility is still deferred.

### 2.7 `take_turn()` is the communication channel

After bootstrap, all communication between the hub and its Purposes flows
through `take_turn(event)`.

- **Hub → Purpose**: `purpose.take_turn(event)` — the hub dispatches events to
  registered Purposes. `BasePurpose.take_turn()` validates the hub token
  before delegating to `_handle_event()`.
- **Purpose → Hub**: `hub.take_turn(event)` — Purposes submit typed events to
  the hub ingress. The hub validates the submitting Purpose's token, consults
  event policy, and acts.

This symmetry is deliberate. Events are the lingua franca of the mesh. Adding
new capabilities means adding new event types and handlers, not proliferating
hub methods.

Purposes must not call `take_turn()` on each other directly. The only valid
source of a hub-authored event is the hub.

### 2.8 Two bootstrap methods stand outside the event model

Two operations cannot be expressed as authenticated events and are therefore
named methods:

**`start_turn()`** — CTO creation is the precondition for the event model. No
`CTOIndex` exists until a CTO is created, so no well-formed event can
represent this act.

**`start_purpose()`** — Purpose registration is the precondition for
participation in the event mesh. No token exists until a Purpose is
registered, so no authenticated event can represent this act.

Everything else flows through `take_turn()`.

### 2.9 Events carry references, not snapshots

Hub-authored event payloads carry a `CTOIndex` — a lightweight routing
reference — not a full CTO snapshot. This keeps the event bus lean regardless
of observation accumulation. Purposes that need full state call
`ttt.librarian.get_cto(turn_id)`.

### 2.10 Persistence is write-ahead with special lifecycle records

For normal hub-authored events, persistence happens before domain delivery.

Two lifecycle events are special:

- `session_started` — written directly to persistence during hub bootstrap
- `session_completed` — written directly to persistence during orderly close

These events bookend the session log and do not go through normal domain
broadcast.

## 3. Public API surface

The complete public-facing API of a running TTT hub is intentionally small:

```text
TTT.start(persistence_purpose, *, strict_profiles=False)
ttt.start_turn(...)
ttt.start_purpose(purpose)
ttt.take_turn(event)
ttt.close(reason="normal")
ttt.librarian.get_cto(turn_id)
````

`ProfileRegistry` is configured directly at process setup — not through the hub. Profiles are process-scoped metadata, hub-independent.

### API clarifications

`ttt.take_turn(event)` is the canonical ingress path for Purpose-originated post-bootstrap events.

Responsibilities:

1. validate event structure
2. authenticate the submitting Purpose
3. verify the event's claimed origin
4. consult event policy
5. dispatch resulting hub-authored events if applicable

All canonical state mutation enters through `take_turn()`.

`TTT.start()` accepts `strict_profiles=True` to activate strict key validation on all profiles at `start_turn()` time.

### Recommended startup sequence

```python
# 1. Register any custom profiles directly on ProfileRegistry (process-scoped)
ProfileRegistry.register(my_profile)

# 2. Start the hub — persistence is required
#    Use InMemoryPersistencePurpose() for tests/dev or Archivist(...) for durable logging
ttt = TTT.start(InMemoryPersistencePurpose())

# 3. Register a submitter Purpose to obtain a hub token
submitter = MySubmitterPurpose()
await ttt.start_purpose(submitter)

# 4. Register any additional domain Purposes
await ttt.start_purpose(other_purpose)

# 5. Begin turn processing — hub_token is required
await ttt.start_turn("conversation", content, submitter.token)
```

## 4. Minimal lifecycle

### 4.1 Start hub

Calling code starts the hub by providing a persistence backend:

```python
ttt = TTT.start(InMemoryPersistencePurpose())
```

The hub validates the persistence contract, assigns persistence credentials, and writes `session_started` directly to persistence.

### 4.2 Start Purposes

Calling code starts one or more domain Purposes via `ttt.start_purpose()`.

Registration:

- associates `Purpose.name`, `Purpose.id`, and `subscriptions`
- generates a cryptographic token and assigns it to the Purpose
- derives and assigns a per-Purpose downlink signature used to validate hub-authored downlink events
- stores a `PurposeRegistration` record keyed by `purpose.id`
- emits `purpose_started`

After registration the Purpose token is non-nullable and the Purpose is ready to receive events.

### 4.3 Call `start_turn()`

A caller invokes `start_turn()` on TTT directly.

Example:

```python
await ttt.start_turn(
    "conversation",
    {
        "speaker": {"id": "usr_a3f9"},
        "text": "hello",
    },
    submitter.token,
)
```

### 4.4 TTT creates CTO

TTT looks up the profile in `ProfileRegistry`, validates the content, applies defaults, creates the CTO (with `last_event_id` set to the `cto_started` event id), stores it in `_ctos`, and emits:

- `cto_started`

### 4.5 Dispatch Purposes

TTT routes `cto_started` to registered Purposes, filtered by profile match, subscription match, and routing rules. Each Purpose receives a per-recipient envelope with its own `hub_token` stamped in.

### 4.6 Purposes propose Deltas

Purposes call `ttt.librarian.get_cto(turn_id)` if they need full content or observations, then submit a `DeltaProposalEvent` to `hub.take_turn()`.

The `CTOIndex.last_event_id` carried in the triggering event payload is available as `based_on_event_id` for the Delta without a separate librarian call.

### 4.7 TTT merges Deltas

TTT validates and merges Deltas (append-only, namespace-scoped), constructs a new CTO instance with updated observations and updated `last_event_id`, and emits:

- `delta_merged`

If a proposed Delta is malformed or invalid, the hub may emit:

- `delta_rejected`

### 4.8 Close session

When orderly shutdown is requested, the hub:

1. emits `session_closing` to registered domain Purposes
2. does not yet wait for DAG-style quiescence in v0.20
3. writes `session_completed` directly to persistence

`session_completed` is the final record in the session log.

## 5. Event taxonomy

### 5.1 Hub-authored event types

- `session_started`
- `purpose_started`
- `cto_started`
- `delta_merged`
- `delta_rejected`
- `session_closing`
- `session_completed`
- `cto_completed` (reserved/deferred terminal lifecycle event)

### 5.2 Purpose-authored event types

- `delta_proposal`
- `purpose_completed`
- `cto_close_request`

### 5.3 Taxonomy notes

`cto_close_request` and `purpose_completed` are accepted as part of the event substrate, but the full DAG/quiescence semantics for them remain deferred.

This means the taxonomy is ahead of the full orchestration layer in a few places by design.

## 6. Persistence model

### 6.1 Ordering guarantees

The persistence ordering contract is:

1. `session_started` is written first
2. every later hub-authored event is persisted before domain delivery
3. `session_completed` is written last

This makes the persisted event stream the authoritative reconstruction log.

### 6.2 Persistence implementations

For development and tests:

- `InMemoryPersistencePurpose`

For durable logging:

- `Archivist`
- Archivist backends such as JSONL and session-document storage

### 6.3 Why persistence is mandatory

The architecture treats persistence as a first-class substrate, not an optional add-on. Without it, the hub cannot satisfy its provenance, replay, and audit commitments.

## 7. What is implemented now vs. deferred

### Implemented in v0.20

- mandatory persistence at startup
- session lifecycle records (`session_started`, `session_closing`, `session_completed`)
- authenticated Purpose registration and routing
- `start_turn()` with required hub token
- `cto_started` and `delta_merged`
- `delta_rejected`
- append-only, namespace-scoped Delta merge
- librarian point lookup
- Archivist-backed durable persistence

### Still deferred

- DAG-based dependency eligibility
- quiescence detection before final session completion
- richer librarian readback/replay APIs
- full semantics for `cto_completed`, `purpose_completed`, and `cto_close_request`
- cross-purpose shared workspaces

## 8. Non-goals for v0.20

TTT v0.20 does not attempt to fully specify:

- domain-specific semantics
- scheduling policy beyond current routing/subscription behavior
- a full workflow engine
- cross-Purpose arbitration semantics beyond append-only namespace enforcement
- final DAG orchestration rules

## 9. Design summary

TTT v0.20 is a small, authority-centered event substrate with mandatory persistence.

The hub creates CTOs, merges Deltas, emits authoritative events, and records those transitions in a write-ahead persistence log. Purposes remain bounded: they observe, reason, and propose. They do not mutate canonical state unilaterally.

That is the point of the architecture: preserve a replayable, auditable record of what the hub canonized as true while keeping domain semantics outside the core.
