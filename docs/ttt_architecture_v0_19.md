# TurnTurnTurn (TTT) — Architecture v0.19

## 0. Positioning

**TurnTurnTurn (TTT)** replaces your sequential pipeline with a dynamic mesh of
tools, each taking dependency-ordered turns to process and enrich your data
nondestructively — with a replayable event stream as the authoritative record
for persistence and regression testing.

TTT is built around a single canonical object:

- **CTO** — Canonical Turn Object

TTT does **not** define domain semantics. It provides:

- authoritative CTO creation
- hub-mediated Delta merge
- typed HubEvents
- Purpose registration and dispatch
- replayable provenance through the event stream

The canonical example profile is **`conversation`**, but TTT is
**profile-based**, not hard-coded to speaker/text semantics.

## 0.1 Invariants

These are the hard commitments. Everything else in this document is mechanism design around them.

- Only TTT may create CTOs.
- Only TTT may make canonical state changes.
- Purposes propose; they do not commit.
- HubEvents are authoritative records of hub-made transitions.
- CTO carries profile identity, not profile behavior.
- Canonical observation history is append-only.
- Event payloads carry references, not full state snapshots.
- `based_on_event_id` is provenance only — not conflict detection.
- Bootstrap methods (`start_turn`, `start_purpose`) stand outside the event model by necessity, not by exception.
- Every HubEvent reaches the persistence sink before any domain Purpose receives it.
- The hub will not start without a registered `CTOPersistencePurposeProtocol` implementor.

## 1. Core nouns

### TTT

The public hub runtime. Start via `TTT.start()`.

TTT is the authority for:

- creating CTOs
- merging Deltas
- emitting HubEvents
- maintaining Purpose registration
- enforcing routing and dispatch rules

The **librarian** (`ttt.librarian`) is the query interface for CTO state.
See §1 (Librarian) and §3.

### start_turn

One of two bootstrap methods on the hub. The other is `start_purpose()`.

`start_turn()` is the ingress point for CTO creation — by external callers,
by application code, and by Purposes (such as Adjacency) that generate new
CTOs as part of their own processing. It is a named method rather than an
event because it is the *precondition* for the event model: no CTOIndex
exists until a CTO is created, so no well-formed event can represent this
act.

A caller invokes `ttt.start_turn(content_profile, content, hub_token)` with
a content profile identifier, content dict, and a hub-issued token
identifying the submitting Purpose. `session_id` is an optional keyword
argument; the hub mints a UUID if absent. TTT looks up the profile in
`ProfileRegistry`, validates the content, applies defaults, creates a CTO,
emits `cto_created`, and dispatches interested Purposes.

Every `start_turn()` caller must hold a valid hub-issued token — obtained by
registering a Purpose via `start_purpose()`. There is no anonymous ingress.
`submitted_by_label` has been retired; attribution is always via Purpose
identity.

### CTO

Canonical Turn Object.

A CTO is the authoritative, canonical work item created by TTT via
`start_turn`. It is frozen — each Delta merge produces a new CTO instance;
the hub replaces the stored instance.

Minimal shape:

- `turn_id`
- `session_id`
- `started_at_ms`
- `content_profile` — `{"id": str, "version": int}`
- `content`
- `observations` — purpose-owned namespaces: `{purpose_name: [obs, ...]}`
- `last_event_id` — the `event_id` of the most recent `cto_created` or
  `delta_merged` event that produced this CTO instance. Set at construction;
  updated on every merge. Carried in `CTOIndex` so Purposes can record it as
  `based_on_event_id` in Delta proposals without a separate librarian call.

The canonical example profile is:

- `content_profile = {"id": "conversation", "version": 1}`
- `content = {"speaker": {"id": str, "role": str, "label": str}, "text": str}`

Profile-scoped accessors (`speaker_id`, `speaker_role`, `speaker_label`,
`text`) are **derived** — resolved at access time by walking `FieldSpec.path`
into the nested content dict. No flat key assumptions.

### Observations and namespaces

Observations are accumulated in per-Purpose namespaces inside the CTO.

Each Purpose writes exclusively to its own namespace (keyed by
`purpose_name`). The hub enforces this at merge time: a Delta proposing
writes outside the submitting Purpose's own namespace is rejected.

TTT currently enforces purpose-owned contribution namespaces. Cross-purpose
observations are deferred pending a concrete use case. The architecture does
not preclude a future shared or reconciled workspace, but no such namespace
is currently normative.

### CTOIndex

A lightweight routing reference to a CTO, carried in HubEvent payloads.

Contains enough for a Purpose to make a dispatch decision — profile type,
identity, session — without the cost of serializing content or observations.
Purposes that need full CTO state call `ttt.librarian.get_cto(turn_id)`.

`CTOIndex` carries `last_event_id`, mirroring `CTO.last_event_id` at the
moment the index was produced. Purposes use this as `based_on_event_id` when
constructing Delta proposals — it records which CTO state the Purpose was
reading when it decided to propose the change, without requiring an extra
librarian call.

`CTOIndex` is a pointer, not a snapshot. It does not carry a moment-in-time
copy of observations or content.

### Purpose

A registered agenda-bearing actor in the TTT mesh.

A Purpose:

- has a semantic `name` (doubles as its observation namespace key)
- has an instance `id`
- receives a hub-assigned `token` at registration — non-nullable after `start_purpose()`
- subscribes to HubEvents by profile and event type
- proposes Deltas into its own namespace
- may read observations from any namespace
- may invoke `start_turn` to submit new CTOs into the mesh
- communicates with the hub exclusively via `hub.take_turn(event)` after bootstrap

A Purpose is **not** a per-turn work parcel.

**`BasePurpose`** is the recommended implementation base. It enforces that
`take_turn()` rejects events whose `hub_token` does not match the assigned
token, closing the point-to-point bypass. Subclasses implement
`_handle_event()` and must not override `take_turn()`.

### Delta

A purpose-proposed change.

A Delta does not mutate canonical state directly. TTT validates and merges
Deltas into CTO observation state using deterministic, append-only rules.
All patch values must be lists.

`based_on_event_id` is a provenance field — the `last_event_id` of the CTO
state the proposing Purpose was reading when it constructed the Delta. Read
from `CTOIndex.last_event_id` in the triggering event payload; no extra
librarian call required. Recorded in the persisted Delta for causal
reconstruction and replay. `None` if the proposing Purpose did not record it.

`based_on_event_id` is **not** a conflict-detection mechanism. Because all
observations are append-only and namespace-scoped, there are no destructive
writes to conflict. Two Purposes proposing Deltas concurrently cannot corrupt
each other's work. `based_on_event_id` answers "what did this Purpose know
when it reasoned?" — a provenance question, not a safety question.

### Event Policy

The hub maintains an internal event policy registry mapping
Purpose-authored event types to optional built-in handlers.

Events without handlers are still accepted and routed through
the hub substrate path but do not trigger built-in hub behavior.

### HubEvent

An authoritative event emitted by TTT.

HubEvents record lifecycle transitions. The event stream is the primary
provenance surface and remains the replay and reconstruction substrate.

Payloads carry a **`CTOIndex`** (not a full CTO snapshot) and provenance
metadata. Purposes that need full CTO state call
`ttt.librarian.get_cto(turn_id)`.

Each event envelope is **per-recipient** — the hub stamps `hub_token` with
the receiving Purpose's assigned token before dispatch. This allows
`BasePurpose.take_turn()` to validate the source and reject point-to-point
calls from other Purposes.

### Librarian

`ttt.librarian` is the query interface for CTO state.

It is a named object on the hub rather than a bare method because its
responsibilities will grow: point lookups today, session readback and
replay queries later (likely against a persistence layer). The hub is an
authority and a router; the librarian is the read path.

Current interface:

- `ttt.librarian.get_cto(turn_id)` — returns the current canonical CTO, or
  None if unknown

Planned interface (TODO):

- `ttt.librarian.get_turns(session_id, last_n=...)` — session readback,
  probably querying against persistence
- Readback requests will generate `ReadbackEvent` or `RewindEvent` so the
  event stream records what was served

### PersistencePurpose and CTOPersistencePurposeProtocol

The persistence seam is the hub's mandatory write-ahead sink.

`CTOPersistencePurposeProtocol` is a structural protocol (duck-typed) that
any persistence backend must satisfy:

- `name: str` — identifies the backend in error messages and payloads
- `id: UUID` — instance identity
- `is_durable: bool` — whether writes survive process restart; the hub
  logs a `UserWarning` at startup if `False`
- `async write_event(event: HubEvent) -> None` — called by `_multicast()`
  before any domain Purpose receives the event; raises on failure

`PersistencePurpose` is the abstract base class for production backends.
It subclasses `BasePurpose` and `abc.ABC`, inheriting hub token validation
and providing a default `_handle_event()` stub. Subclasses implement
`write_event()`.

`InMemoryPersistencePurpose` ships in core as a development backend
(`is_durable=False`). It appends serialized event dicts to an in-memory
list and deduplicates by `event_id`. Not suitable for production.

The persistence Purpose is registered at `TTT.start()` time, not via
`start_purpose()`. The hub calls `_bootstrap_persister()` immediately —
assigning a hub token and downlink signature, emitting `session_started`
(written to the persistence backend before any other event), and storing
the registration outside `self.registrations` so it is not included in
domain Purpose broadcast. Callers pass the persistence Purpose as the
first positional argument to `TTT.start()`; omitting it raises `TypeError`.

## 2. Core principles

### 2.1 TTT is authoritative

Only TTT may create CTOs or mutate canonical CTO state.

Purposes propose changes. TTT decides what becomes canonical.

### 2.2 Append-only by default

Canonical history is preserved.

TTT does not silently overwrite prior contributions. Merge behavior is
deterministic and history-preserving. All Delta patch values must be lists;
the hub extends, never replaces.

### 2.3 Provenance is primarily in the event stream

The authoritative answer to "who contributed what, when" comes from HubEvents
and replayable event history, not from stuffing provenance into every
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
subscriptions or eligibility. The full dispatch order is:

1. **Profile match** — does this Purpose handle this CTO's profile?
2. **Subscription match** — has this Purpose subscribed to this event type?
3. **DAG eligibility** — are this Purpose's declared dependencies satisfied?

### 2.7 `take_turn()` is the communication channel

After bootstrap, all communication between the hub and its Purposes flows
through a single method: `take_turn(event)`.

- **Hub → Purpose**: `purpose.take_turn(event)` — the hub dispatches events
  to registered Purposes. `BasePurpose.take_turn()` validates the hub token
  before delegating to `_handle_event()`.
- **Purpose → Hub**: `hub.take_turn(event)` — Purposes submit typed events
  to the hub ingress. The hub validates the submitting Purpose's token,
  routes by event type, and acts.

This symmetry is deliberate. Events are the lingua franca of the mesh. Every
capability — Delta proposals, subscription updates, dependency declarations,
unicast routing requests — is expressed as a typed event. The API surface
cannot be broken by extension: adding a new capability means adding a new
event type, not a new method.

Purposes must not call `take_turn()` on each other directly. The only valid
source of a HubEvent is the hub. `BasePurpose.take_turn()` enforces this via
hub token validation — point-to-point calls will not carry a valid token and
will raise `UnauthorizedDispatchError`.

### 2.8 Two bootstrap methods stand outside the event model

Two operations cannot be expressed as events and are therefore named methods:

**`start_turn()`** — CTO creation is the precondition for the event model.
No CTOIndex exists until a CTO is created, so no well-formed event can
represent this act. Available to external callers, application code, and
Purposes alike.

**`start_purpose()`** — Purpose registration is the precondition for
participation in the event mesh. No token exists until a Purpose is
registered, so no authenticated event can represent this act.

Everything else flows through `take_turn()`.

### 2.9 Events carry references, not snapshots

HubEvent payloads carry a `CTOIndex` — a lightweight routing reference —
not a full CTO snapshot. This keeps the event bus lean regardless of
observation accumulation. Purposes that need full state call
`ttt.librarian.get_cto(turn_id)`. `ctoPersistPurpose` is the canonical
consumer of this pattern.

## 3. Public API surface

The complete public-facing API of a running TTT hub:

```
TTT.start(persistence_purpose)     # factory + service start; persistence_purpose required
ttt.start_turn(...)                # bootstrap a CTO into the mesh
ttt.start_purpose(purpose)         # bootstrap a Purpose into the mesh
ttt.take_turn(event)               # all post-bootstrap communication, both directions
ttt.librarian.get_cto(turn_id)     # point query (synchronous, in-memory)
```

`ProfileRegistry` is called directly at process setup — not through the hub.
Profiles are process-scoped metadata, hub-independent.

`ttt.librarian` is a named object on the hub. It is the read path for CTO
state and will grow to support session readback queries against persistence.

### API clarifications

`ttt.take_turn(event)` is the canonical ingress path for Purpose-originated
post-bootstrap events.

Responsibilities:

1. validate event structure
2. authenticate the submitting Purpose
3. verify the event's claimed origin
4. dispatch to the appropriate handler

All canonical state mutation must enter through `take_turn()`.
Direct mutation helpers remain internal implementation details.

`TTT.start()` accepts `strict_profiles=True` to activate strict key
validation on all profiles at `start_turn()` time.

### Recommended startup sequence

```python
# 1. Register any custom profiles directly on ProfileRegistry (process-scoped)
ProfileRegistry.register(my_profile)

# 2. Start the hub — persistence_purpose is required
ttt = TTT.start(MyPersistencePurpose())

# 3. Register a submitter Purpose to obtain a hub token
submitter = MySubmitterPurpose()
await ttt.start_purpose(submitter)

# 4. Register any additional domain Purposes
await ttt.start_purpose(other_purpose)

# 5. Begin turn processing — hub_token is required
await ttt.start_turn("conversation", content, submitter.token)
```

The persistence Purpose is bootstrapped inside `TTT.start()` before any
other registration or turn processing. `session_started` is the first event
written to the persistence backend; it is not broadcast to domain Purposes.
Every subsequent event passes through `write_event()` before domain delivery.

## 4. Minimal lifecycle

### 4.1 Start Purposes

Calling code starts one or more Purposes via `ttt.start_purpose()`.

Registration:

- associates `Purpose.name`, `Purpose.id`, and `subscriptions`
- generates a cryptographic token and assigns it to the Purpose via
  `BasePurpose._assign_token()`
- derives and assigns a per-Purpose `downlink_signature` used to validate
  hub-authored downlink events
- stores a `PurposeRegistration` record keyed by `purpose.id`

After registration the Purpose's token is non-nullable and the Purpose is
ready to receive events.

### 4.2 Start session

TTT creates or accepts session context.

### 4.3 Call start_turn

A caller invokes `start_turn` on TTT directly. External callers, application
code, and Purposes may all call `start_turn`.

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

TTT looks up the profile in `ProfileRegistry`, validates the content, applies
defaults, creates the CTO (with `last_event_id` set to the `cto_created`
event_id), stores it in `_ctos`, and emits:

- `cto_created`

### 4.5 Dispatch Purposes

TTT routes `cto_created` to registered Purposes, filtered by profile match,
subscription match, and DAG eligibility. Each Purpose receives a
per-recipient envelope with its own `hub_token` stamped in.

### 4.6 Purposes propose Deltas

Purposes call `ttt.librarian.get_cto(turn_id)` if they need full content or
observations, then submit a `DeltaProposalEvent` to `hub.take_turn()`.

The `CTOIndex.last_event_id` carried in the triggering event payload is
available as `based_on_event_id` for the Delta without a separate librarian
call.

### 4.7 TTT merges Deltas

TTT validates and merges Deltas (append-only, namespace-scoped), constructs
a new CTO instance with updated observations and updated `last_event_id`,
and emits:

- `delta_merged`

### 4.8 Repeat until quiescent

TTT continues routing and merge/dispatch cycles until no further eligible
work remains.

## 5. Diagrams

### 5.1 System shape

```text
external caller / app / Purpose
          │
          ├─ start_turn(session_id, content_profile, content, ...)
          │
          ├─ hub.take_turn(DeltaProposalEvent | SubscriptionUpdateEvent | ...)
          │
          ▼
┌─────────────────────────────────────┐
│                TTT                  │
│                                     │
│  authoritative hub runtime          │
│  - validate content                 │
│  - create CTO                       │
│  - merge Deltas                     │
│  - emit HubEvents                   │
│  - enforce registry/routing         │
│                                     │
│  ttt.librarian                      │
│  - get_cto(turn_id)                 │
└─────────────────────────────────────┘
      │                │
      ▼                ▼
  profile +        DAG
  subscriptions    (eligibility)
  (interest)           │
      │                │
      └──────┬──────────┘
             ▼
         Purposes
         (purpose.take_turn(event))
```

### 5.2 Creation boundary

```text
start_turn(...)  --invoked on-->  TTT
                                    │
                                    ├─ look up profile in ProfileRegistry
                                    ├─ validate + apply defaults
                                    ├─ mint cto_created_event_id
                                    ├─ create CTO (last_event_id = cto_created_event_id)
                                    └─ emit cto_created { cto_index: ..., submitted_by: ... }
```

### 5.3 Canonical event flow

```text
start_turn
   ↓
cto_created  { cto_index (carries last_event_id), submitted_by }
   ↓
Purpose(s) _handle_event(event)   ← validated by take_turn() via hub_token
   ↓
hub.take_turn(DeltaProposalEvent)   ← Purpose submits via hub ingress
   ↓
delta_merged  { delta (carries based_on_event_id), cto_index (carries last_event_id) }
   ↓
follow-on Purpose dispatch
```

### 5.4 Unicast routing (example)

```text
tmDetectorPurpose notices a trace mutation
   ↓
hub.take_turn(UnicastEvent(recipient="adjacency", payload=tmDetectorObservation))
   ↓
hub routes to AdjacencyPurpose only
   ↓
AdjacencyPurpose prompts implicated LLM
   ↓
hub.take_turn(DeltaProposalEvent) → delta_merged
   ↓
ctoPersistPurpose (dependencies=["*"]) receives final delta_merged
   ↓
ttt.librarian.get_cto(turn_id) → serialize and persist
```

## 6. Canonical example profile: `conversation`

TTT is profile-based, but `conversation` remains the canonical example
because it is simple, legible, and central to Adjacency.

### 6.1 The profile system

A `Profile` is a self-contained schema object that owns validation, default
application, and accessor resolution for one content shape. Profiles are
registered in `ProfileRegistry` — a process-scoped class-level registry,
independent of any hub instance. The hub consults it at `start_turn()` time;
`CTO.__getattr__` consults it at attribute access time.

`ProfileRegistry` is called directly — not through the hub. Profiles are
declarative metadata registered once at process startup.

The CTO carries only identifying data — no object references, no code:

```python
content_profile = {"id": "conversation", "version": 1}
```

This is fully serializable and loggable as-is. `CTO.__getattr__` dispatches
to `ProfileRegistry.resolve(id, version, name, content)` for unknown
attribute lookups. No profile-specific code lives in `CTO` or `hub.py`.

To add a new profile: construct a `Profile` with `FieldSpec` declarations,
call `ProfileRegistry.register(profile)` at process startup. No core module
changes required.

### 6.2 Key convention

The conversation profile uses the **parent_child flat accessor convention**
(max depth 2). CTO accessor names are derived from the content path:
`speaker.id` → `speaker_id`. The actual content dict is nested;
`FieldSpec.path` is the source of truth for traversal. Enforced when
`strict_profiles=True` on the hub or `strict=True` on the profile;
documented convention otherwise.

### 6.3 Content shape

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

### 6.4 Accessor dispatch

Content is nested; CTO accessors are flat, following the parent_child
convention. `cto.speaker_id` resolves to `content["speaker"]["id"]` by
walking the path tuple `("speaker", "id")` declared in the profile's
`FieldSpec`:

```python
cto.speaker_id     # → content["speaker"]["id"]
cto.speaker_role   # → content["speaker"]["role"]
cto.speaker_label  # → content["speaker"]["label"]
cto.text           # → content["text"]
```

Unknown attribute names raise `AttributeError` as normal. Accessors for
unknown profiles raise `AttributeError` — there is no cross-profile fallback.

### 6.5 Computed accessors

Not supported in v0. All accessors walk `FieldSpec.path` into the nested
content dict. When computed accessors are needed (fields derived from
multiple content keys), override `Profile.resolve()` on a subclass and
register the subclass. No core changes required.

### 6.6 strict_profiles

`TTT.start(strict_profiles=True)` activates strict key validation on all
profiles at `start_turn()` time. Per-profile `strict=True` activates it for
that profile regardless of the hub setting.

## 7. Event taxonomy (v0.19)

### Event model clarification

TTT uses a typed event model with structured payload objects.

All events satisfy this minimal contract:

```python
class EventProtocol(Protocol):
    event_type: HubEventType
    event_id: UUID
    started_at_ms: int
    payload: EventPayloadProtocol
```

Payloads satisfy:

```python
class EventPayloadProtocol(Protocol):
    def as_dict(self) -> dict[str, Any]: ...
```

This keeps serialization, logging, and persistence on one explicit path.

### Purpose-originated event contract

Purpose-submitted events satisfy a stricter contract:

```python
class PurposeEventProtocol(EventProtocol, Protocol):
    purpose_id: UUID
    purpose_name: str
    hub_token: str
```

When the hub receives a Purpose event it validates:

1. `hub_token` resolves to a registered Purpose
2. `purpose_id` matches the registered Purpose
3. `purpose_name` matches the registered Purpose

Events failing these checks are rejected with
`UnauthorizedDispatchError`.

### `session_started`

The hub has initialized and the persistence backend is ready.

Emitted by `_bootstrap_persister()` immediately after the persistence
Purpose receives its hub token. Written directly to `write_event()` —
not routed through `_multicast()`, not delivered to domain Purposes.
This is the first event in every session's durable record.

Payload includes:

- `hub_id` — UUID of this hub instance
- `ttt_version` — package version string
- `persister_name` — `persistence_purpose.name`
- `persister_id` — `persistence_purpose.id` as string
- `persister_is_durable` — `persistence_purpose.is_durable`
- `strict_profiles` — hub strict_profiles flag
- `_schema` / `_v` metadata

### `cto_created`

A new CTO now exists and is canonical.

Payload includes:

- `cto_index` — `CTOIndex` dict (turn_id, session_id, content_profile,
  started_at_ms, last_event_id)
- submitter attribution (`submitted_by_purpose_id`,
  `submitted_by_purpose_name`) — always present; every `start_turn()`
  caller must hold a valid hub token. `submitted_by_label` has been retired.
- `_schema` / `_v` metadata for deserializer dispatch

### `delta_merged`

TTT has accepted and merged a Delta into canonical state.

Payload includes:

- `delta` — full serialized Delta (provenance record, includes
  `based_on_event_id`)
- `cto_index` — `CTOIndex` dict reflecting the post-merge CTO state
  (includes updated `last_event_id`)
- `_schema` / `_v` metadata

### `delta_proposal`

A Purpose-submitted request to merge a Delta. Submitted via
`hub.take_turn()`. The hub validates the submitting Purpose, verifies the
claimed sender identity, routes to internal `_merge_delta()`, and emits
`delta_merged` on success.

`DeltaProposalPayload` carries the proposed `Delta` and serializes via
`.as_dict()` like all event payloads.

This event replaces direct `merge_delta()` calls as the public-facing
mechanism.

### `purpose_started`

TTT has accepted a Purpose registration.

Emitted by `start_purpose()` and delivered via `_multicast()` to all
registered domain Purposes. Payload includes `purpose_id`,
`purpose_name`, and `_schema` / `_v` metadata.

Also emitted for the persistence Purpose during `_bootstrap_persister()`,
written directly via `write_event()` before broadcast begins.

### `subscription_update` (TODO)

A Purpose-submitted request to update its event subscriptions. Submitted
via `hub.take_turn()`. Replaces any hypothetical `update_subscriptions()`
method.

### `dependency_update` (TODO)

A Purpose-submitted request to update its DAG dependency declarations.
Submitted via `hub.take_turn()`. Allows a Purpose to declare or revise what
must have completed before it is eligible to fire on a given CTO.

### `purpose_completed`

Open question — see §10.

This section should stay intentionally small.

## 8. Identification model

### Purpose identity

Each Purpose has:

- `name` — semantic kind, e.g. `"ca"`, `"embeddingizer"`, `"socratic"`
- `id` — concrete instance UUID
- `token` — hub-assigned cryptographic token, assigned at `start_purpose()`,
  non-nullable after registration

Many Purposes may share the same `name`. `id` distinguishes instances.
`token` authenticates hub dispatch in both directions.

### CTO identity

`turn_id` is the canonical CTO identity key.

`last_event_id` is the version handle — the `event_id` of the most recent
hub event that produced this CTO instance. Set to the `cto_created` event_id
at construction; updated to the `delta_merged` event_id on each merge.

### Event identity

Each HubEvent has its own `event_id`.

### Hub downlink verification

Hub-authored downlink events carry a `downlink_signature` scoped to the hub
instance and registered Purpose.

Purpose: detect hub-looking events that did not actually originate from the
hub and discourage direct Purpose-to-Purpose bypasses.

This mechanism is for route integrity and architecture enforcement, not
adversarial cryptographic security.

Recommended construction: derive the signature using an HMAC-style function
with a hub-private secret as key and Purpose-specific material (at minimum
`purpose_token` and `purpose_id`) as input.

### CTOIndex

`CTOIndex` is the lightweight event-payload form of CTO identity. Carries
`turn_id`, `session_id`, `content_profile`, `started_at_ms`, and
`last_event_id`. Used by Purposes for routing decisions and for recording
`based_on_event_id` in Delta proposals without a separate librarian call.

## 9. Module map

Source of truth lives in code.

Primary modules:

- `hub.py` — TTT runtime; `librarian.py` or inline `Librarian` class
- `base_purpose.py` — BasePurpose abstract base class; hub token validation;
  `_handle_event()` override point
- `persistence.py` — `PersistencePurpose` abstract base; `InMemoryPersistencePurpose`
  development backend; `CTOPersistencePurposeProtocol` lives in `protocols.py`
- `protocols.py` — EventProtocol, PurposeEventProtocol,
  EventPayloadProtocol, CTOPersistencePurposeProtocol, and related structural contracts
- `cto.py` — CTO and CTOIndex; no profile-specific code
- `profile.py` — Profile, ProfileRegistry, FieldSpec, path-walking helpers
- `events/` — event definitions and payload classes
  - `events/hub_events.py` — hub-authored event types and shared contracts
  - `events/purpose_events.py` — Purpose-originated event types
  - `events/__init__.py` — public re-exports
- `delta.py` — Delta
- `registry.py` — PurposeRegistration
- `errors.py` — TTTError, UnauthorizedDispatchError,
  UnknownEventTypeError, UnboundPurposeError, PersistenceFailureError
- `dag.py` — eligibility model (stub)
- `ids.py` — identifier utilities (stub)

This document is only the front door.

## 10. Non-goals for v0.19

TTT v0.19 does not yet attempt to fully specify:

- cross-process transport
- durable persistence layout (schema, storage backend, migration)
- auth policy beyond hub token seam
- domain semantics for observations
- final naming for `purpose_completed` event
- DAG eligibility layer (stub only)
- hub-local diagnostic logging for unauthenticated dispatch failures
- `SubscriptionUpdateEvent` and `DependencyUpdateEvent`
  (taxonomy settled, implementation pending)
- custom event type registration by consuming projects
- `ttt.librarian.get_turns()` readback interface
- multiple concurrent persistence backends

## 11. Immediate open questions

- **DAG layer** — `dag.py` remains a stub. Design deferred until Adjacency
  integration drives real dependency declarations. The `dependencies=["*"]`
  terminal-node pattern for `ctoPersistPurpose` is the first concrete
  requirement.
- **Error events for unauthenticated failures** — current recommendation is
  to raise exceptions only. Future work may add a hub-local diagnostic sink
  and optionally authenticated `ErrorEvent` emission.
- **Custom event registration** — mechanism for consuming projects to extend
  the hub routing table without living in the TTT namespace remains open.
- **Cross-purpose observations** — whether a shared or reconciled workspace
  is needed for Purposes to build on each other's observations is deferred
  pending a concrete use case. The architecture does not preclude it; no
  mechanism is currently specified.
- **Unicast routing** — `tmDetectorPurpose` example in §5.4 illustrates the
  pattern. A Purpose submits a unicast event via `hub.take_turn()`; the hub
  routes it to a single named recipient. Mechanism (declared recipient in
  event payload, or subscription-filter-derived) is open.
- **`ttt.librarian.get_turns()` readback** — likely queries against
  persistence. Whether readback requests generate `ReadbackEvent` /
  `RewindEvent` for the event stream is open.
- **`purpose_completed`** — does this event survive or get replaced by
  something cleaner?
- **Profile registry strict enforcement** — the `parent_child` key convention
  depth check in `Profile.validate(strict=True)` is a placeholder. Full
  enforcement deferred pending real usage.
- **Declarative profile system** — profiles-as-pure-data, loadable from JSON
  or YAML. Design sketched in `profile.py` module docstring. Seam: the three
  stable method signatures `Profile.validate()`, `Profile.apply_defaults()`,
  `Profile.resolve()` must not change when this lands.
- **Persister recovery detection** — currently the hub has no mechanism to
  detect that a persistence backend has recovered after a `PersistenceFailureError`.
  Whether recovery is signaled via a new bootstrap call, a sentinel event, or
  a health-check protocol is open. For now, a `PersistenceFailureError` is
  terminal for the hub instance.
- **`write_event()` idempotency enforcement** — `InMemoryPersistencePurpose`
  deduplicates by `event_id`. Whether the hub should enforce idempotency at
  the call site (e.g. by tracking emitted `event_id`s) or delegate it entirely
  to the backend is open.
- **`ReadbackRequestEvent`** — when `ttt.librarian.get_turns()` lands, should
  the read request itself be recorded in the event stream? Recording it enables
  full audit of what was served and when, but adds noise to the primary record.
  Design deferred.
- **Multiple persistence backends** — the current model is a single mandatory
  persister. Whether "all must confirm" fan-out (stronger durability) or
  "primary + async replica" patterns belong in core or in a composing wrapper
  is open.

## 12. Migration notes

### v0.19 (this revision)

**Persistence architecture:**
- `TTT.start()` now requires a `CTOPersistencePurposeProtocol` implementor
  as its first positional argument. Omitting it raises `TypeError`. This
  is an intentional hard requirement — there is no anonymous or persistence-free
  hub start.
- `PersistencePurpose(BasePurpose, abc.ABC)` added as the abstract base for
  production persistence backends. `InMemoryPersistencePurpose` ships in core
  as a development backend (`is_durable=False`).
- `CTOPersistencePurposeProtocol` added to `protocols.py`.
- `PersistenceFailureError(TTTError)` added to `errors.py`. Raised when
  `write_event()` throws; carries `persister_name` and `event_id`. Halts
  domain delivery — no Purpose receives an event that was not durably written.
- `_multicast()` rewritten with two phases: Phase 1 calls
  `persistence_purpose.write_event()` unconditionally; Phase 2 broadcasts to
  domain Purposes. Phase 2 does not run if Phase 1 raises.
- `session_started` event added. Emitted during `_bootstrap_persister()`;
  written to the persistence backend only, not broadcast to domain Purposes.
  First event in every session's durable record.

**`start_turn()` signature change:**
- `start_turn(content_profile, content, hub_token, *, session_id=None)`
  replaces the previous keyword-argument-heavy signature.
- `hub_token` is now a required positional argument. Every caller must hold
  a valid hub-issued token. There is no anonymous ingress.
- `session_id` moves to a keyword-only optional; the hub mints a UUID if absent.
- `submitted_by_label` retired entirely. Submitter attribution in
  `cto_created` payload is always via `submitted_by_purpose_id` and
  `submitted_by_purpose_name`, resolved from the token.

**`purpose_started` now emitted:**
- `start_purpose()` now emits `purpose_started` with `PurposeStartedPayload`
  via `_multicast()`. Previously the taxonomy entry was settled but emission
  was pending.

**`ttt.librarian` landed:**
- `ttt.librarian` is now a named `Librarian` object on the hub (not a bare
  method). `ttt.librarian.get_cto(turn_id)` is the stable read path.
  Removed from non-goals.

### v0.18 (from v0.17)

**API surface:**
- `TTT.create()` → `TTT.start()`. Same semantics; renamed to reflect that
  TTT is a service layer, not just an object factory. Future: may expose a
  TCP/IP interface.
- `TTT.register_purpose()` → `ttt.start_purpose()`. Symmetric with
  `start_turn()` — both bootstrap a participant that cannot yet use
  `take_turn()` because the prerequisite (token / CTOIndex) does not yet
  exist.
- `TTT.register_profile()` retired. `ProfileRegistry.register()` called
  directly at process startup. Profiles are process-scoped, hub-independent.
- `TTT.get_cto()` retired from hub surface. Replaced by
  `ttt.librarian.get_cto()`. The hub is an authority and router; the
  librarian is the read path.
- `TTT.merge_delta()` retired from public API. Replaced by
  `hub.take_turn(DeltaProposalEvent(...))`. Exists only as internal
  `_merge_delta()`.
- `hub.take_turn(event)` is the unified Purpose → hub ingress.
- event definitions move from `events.py` to the `events/` package, with
  imports preserved through re-exports.

**Communication model:**
- `take_turn()` is now the explicit two-way communication channel:
  `hub.take_turn(event)` for Purpose → hub; `purpose.take_turn(event)` for
  hub → Purpose. Both directions validate the hub token.
- The two bootstrap methods (`start_turn`, `start_purpose`) stand outside
  the event model because their prerequisites (CTOIndex, token) do not yet
  exist at the time they are called. This is structural, not an exception.

**Observations:**
- Hub enforces purpose-owned namespaces at merge time: a Delta proposing
  writes outside the submitting Purpose's own namespace is rejected.
- `based_on_event_id` on Delta reframed as **provenance**, not conflict
  detection. There are no destructive writes in the observation model;
  `based_on_event_id` records causal context for replay and debugging, not
  safety.
- `stale_delta` removed from `delta_merged` payload. The concept was
  borrowed from mutable-state concurrency and does not apply to
  append-only, namespace-scoped observations.

**Delta versioning (landed in v0.18):**
- `CTO.last_event_id` — version handle, set at construction and updated on
  every merge.
- `CTOIndex.last_event_id` — mirrors CTO; carried in event payload so
  Purposes can record it as `based_on_event_id` without a librarian call.
- `Delta.based_on_event_id` — provenance field, optional (`None` if not
  recorded).

**Dispatch:**
- Profile match added as dispatch filter layer 1, before subscription match
  and DAG eligibility. A Purpose registered for `"conversation"` CTOs does
  not receive dispatch for other profiles.

**Event taxonomy:**
- `purpose_registered` → `purpose_started` (not yet emitted).
- `delta_proposal`, `subscription_update`, `dependency_update` added to
  taxonomy as TODOs.

### v0.17 (from v0.16)

- `BasePurpose` added — abstract base class for all Purposes.
- Hub token assigned at registration, non-nullable after
  `TTT.register_purpose()`.
- `take_turn()` validates `hub_token` on every call.
- HubEvent payloads carry `CTOIndex` instead of full CTO snapshot.
- `CTOIndex` added — lightweight routing reference.
- `CTO.to_index()` added.
- `TTT.get_cto(turn_id)` added.
- `TTT._ctos` added — canonical CTO store.
- `_multicast()` constructs per-recipient envelopes.
- `errors.py` filled in.
- Profile `validate()`, `apply_defaults()`, `resolve()` walk `FieldSpec.path`.
- Path-walking helpers added to `profile.py`.
- `merge_delta()` added to TTT.
- `payload_delta_merged()` added to `events.py`.

### v0.16 (from v0.15)

- From conversational turn processing to profile-based canonical work-item
  routing.
- From `TurnSnargle` + `submit_snargle()` to `start_turn()`.
- From `turn_received` to `cto_created`.
- From `purpose_id` as overloaded type/instance language to `Purpose.name`
  + `Purpose.id`.
- From flat `content["speaker_id"]` to nested `content["speaker"]["id"]`.
- From `CTO.speaker` to `CTO.speaker_id`, `CTO.speaker_role`,
  `CTO.speaker_label`.
- From ad-hoc `validate_content_profile()` to `Profile` / `ProfileRegistry`.
- `content_profile` changed from string to plain dict.
- `_speaker_registry` replaced by opaque `_session_contexts`.

It preserves:

- hub-authoritative merge semantics
- append-only observation history
- event-stream provenance as primary record
- switch-style routing plus DAG-gated eligibility


### Documentation split note

This architecture document is the normative design surface.
Explanatory runtime walkthroughs — such as event lifecycle diagrams,
end-to-end flow examples, and extension-oriented developer guidance — belong
in MkDocs developer documentation near the code they describe.
