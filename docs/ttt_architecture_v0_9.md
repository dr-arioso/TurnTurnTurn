# TurnTurnTurn (TTT) — Architecture Document
## Version 0.7 — March 2026
### Source: Design session between Bill and Claude (Anthropic)


> **v0.6 note:** Reinstates the **provider registration + subscriptions** layer from v0.4 as an explicit hub capability (TTT.register / ChangeSubscriptionsEvent) while keeping the v0.2 core dataclasses (CTO/Observation/Delta) and HubEvent stream as the authoritative record.

---

## 0. Background and Motivation

This document describes the architecture of **TurnTurnTurn (TTT)**, a lightweight,
domain-neutral Python middleware library for conversational turn processing. It emerged
from design work on **Adjacency** (a structured elicitation research instrument) and
the need for a reusable infrastructure layer that could serve that project and others.

An earlier document (*Alignment Middleware for Human–LLM Dialogue*) sketched a broader
alignment and detection pipeline. TTT is not that system. TTT is the foundational
layer that such a system would be built on — the part that handles canonical turn
representation, enrichment, event routing, and persistence, without presupposing any
particular analytical purpose.

Sections of the earlier document that remain relevant — particularly the trace mutation
detection signals, alignment snapshot design, DecisionCard/provenance accumulator, and
the integration roadmap — are preserved in **Appendix A** of this document for
reference. Those components are best understood as **Purpose implementations** that
would run on top of TTT, not as architectural concerns of TTT itself.

---

## 1. Design Principles

**Raw text is the substrate. The CTO is the unit of computation.**
Every turn becomes a Canonical Turn Object immediately on receipt. All downstream
processing operates based on CTOs, never on raw strings.

**The event stream is the authoritative record.**
CTOs and Deltas travel on typed events. The event stream is what you replay to
reconstruct any derived artifact. Full CTO observation state is always derivable
from the event stream.

**Append-only. Never override.**
The CTO identity fields are immutable at construction. The `observations` dict is
written once per owned namespace and appended-to for shared namespaces. Nobody
overrides anyone else. Everyone just takes their turn.

**Owned vs shared namespaces.**
Each Purpose owns one namespace in `cto.observations` — written once, single
writer. Shared namespaces are always lists — TTT appends each contribution
regardless of count. A single contributor produces a list of one. Conflict
resolution is never TTT's concern; that belongs to a resolver operating
downstream.

**Provenance is a query, not a field.**
Who contributed what, and when, is answerable from the event stream. The
`observations` dict carries only values — clean, uncluttered by attribution
metadata. TRTPurpose persists every event; provenance views are queries or
formatted log entries derived from that stream.

**Domain-neutral core.**
TTT knows nothing about trace mutations, conversation analysis, LLM alignment,
or any other research domain. Those concerns belong in Purpose implementations.
The core ships with exactly one built-in Purpose adapter: **TRTPurpose**
(the TTT integration point for TurnReTurn).

**`take_turn` is the one true path.**
All communication flows through `take_turn`, including registration and
subscription management. Convenience methods like `ttt.register()` are
syntactic sugar that construct and dispatch events internally. Under the hood
it is always events.

**Loosely coupled via declared dependencies.**
Purposes declare what other Purposes they depend on. TTT manages execution
order via a DAG resolver. Purposes never call each other directly.

**TTT is a domain-specific micro actor system built on asyncio.**
The architecture is conceptually an Actor model: every participant has a typed
message interface, communicates via events, and does not know about other
participants' implementations. Implemented directly on asyncio + dataclasses
rather than an actor framework, which would add overhead without benefit at
the expected scale.

---

## 2. Conceptual Model

```
Calling code (e.g. Adjacency session runner)
    │
    │  ttt.register(purpose)          ← convenience wrapper
    │  take_turn(HubEvent("register")) ← what actually happens
    │
    │  take_turn(HubEvent("turn_observed", ...))
    ▼
┌──────────────────────────────────────────────┐
│                TurnTurnTurn                  │
│                                              │
│  1. Construct CTO from turn_observed event   │
│  2. Resolve DAG — find eligible Purposes     │
│  3. Dispatch concurrently via asyncio        │
│  4. Receive purpose_complete events back     │
│  5. If delta present:                        │
│     a. Validate token                        │
│     b. Write purpose_data →                  │
│           observations[purpose_id]           │
│     c. Append shared_data →                  │
│           observations[schema_id]            │
│     d. Advance DAG — check new eligibles     │
│  6. Emit purpose_resolved to subscribers     │
│     (filtered by declared interest/wildcard) │
│  7. When DAG exhausted:                      │
│     emit turn_processing_complete            │
│     or turn_processing_incomplete (timeout)  │
└──────────────────────────────────────────────┘
         │                        ▲
         │ take_turn(HubEvent)    │ take_turn(HubEvent)
         ▼                        │
  ┌────────────┐  ┌─────────────────┐  ┌───────────────┐
  │ TRTPurpose │  │  CAPurpose      │  │  TMPurpose    │
  │ (built-in) │  │  depends_on=[]  │  │  depends_on=  │
  └────────────┘  └─────────────────┘  │  ["embed","ca"]│
        │                              └───────────────┘
        │                                      │
        ▼                              may emit speaker_feedback
  ┌─────────────────────────┐          back to calling code
  │      TurnReTurn         │
  │                         │
  │  Stores:                │
  │  ├── FileStore          │
  │  │   ├── JSONLBackend   │
  │  │   ├── JSONBackend    │
  │  │   └── PlainTextBackend│
  │  ├── MemoryStore        │
  │  │   └── MessageDictBackend│
  │  └── SQLStore           │
  │      ├── SQLiteBackend  │
  │      └── PostgresBackend│
  │                         │
  │  Query views:           │
  │  ├── provenance()       │
  │  ├── session_replay()   │
  │  └── purpose_audit()    │
  └─────────────────────────┘
```

---

## 3. Core Protocols

### 3.1 TurnTakerProtocol

The fundamental interface. Everything that participates in the event stream
implements it: Purposes, TTT itself, and calling code.

```python
class TurnTakerProtocol(Protocol):
    async def take_turn(self, event: HubEvent) -> None: ...
```

`take_turn` accepts a `HubEvent` and returns nothing. Participants that want
to send results or feedback back to TTT call `ttt.take_turn(event)` directly.
The interface is uniform across all participants — no special return types,
no polymorphic signatures.

### 3.2 PurposeProtocol

Extends `TurnTakerProtocol`. Purpose metadata is declared as class attributes
and communicated to TTT via the `register` event.

```python
class PurposeProtocol(TurnTakerProtocol, Protocol):
    purpose_id: str      # stable machine identifier; becomes namespace key
    purpose_name: str    # human-readable label for logging and audit views

    async def take_turn(self, event: HubEvent) -> None: ...
```

Registration metadata (`private`, `depends_on`, `subscriptions`) is carried
in the `register` event payload. This allows the same Purpose implementation
to be registered with different configurations in different sessions.

### 3.3 StoreProtocol

```python
class StoreProtocol(Protocol):
    async def write(self, event: HubEvent) -> None: ...
    async def flush(self) -> None: ...
    async def query(self, **kwargs) -> list[dict]: ...  # optional
```

---

## 4. Event Model

TTT/Adjacency now treats the **hub-emitted event stream** as the authoritative record of turn processing. Events are emitted on each hub state transition and are persisted by downstream stores (e.g., TurnReTurn backends).

### 4.1 HubEvent (authoritative event record)

```python
@dataclass
class HubEvent:
    event_id:   str            # 24-char hex (secrets.token_hex(12))
    event_type: EventType      # Enum (pipeline + annotation)
    token_id:   str | None     # CTO token_id when event is turn-scoped
    payload:    dict[str, Any] # event-specific; convention: includes _schema and _v
    timestamp:  float          # unix epoch
```

Events are intentionally small and JSON-safe (or trivially serializable via `to_dict()` on embedded objects). Payloads should follow the `_schema` + `_v` convention for future migration/debugging.

### 4.2 EventType vocabulary (v0.2)

Pipeline (DAG) lifecycle:

- `turn_received`
- `purpose_fired`
- `provider_complete`
- `delta_merged`
- `purpose_complete`

Out-of-band annotation:

- `turn_observation_recorded`

Notes:
- The earlier **register/registered/subscription_update** lifecycle described in v0.4 is deferred; the v0.2 core assumes an in-process hub that already knows its providers for the session.
- Authentication-by-registration-token is therefore not part of the v0.2 event model (the hub is the sole emitter of authoritative lifecycle events).

### 4.3 Provider registration and subscriptions (hub-managed)

Although the **HubEvent** stream remains the authoritative record, TTT supports a **provider registration** layer to make the system extensible and safe across process boundaries.

#### 4.3.1 TTT.register()

A Purpose/Provider registers itself with the hub by providing:

- `purpose_id: str` (stable identifier; used as the provider namespace)
- `subscriptions: list[str]` (event patterns; may include globs, e.g., `Events.*`)
- optional `capabilities` (e.g., whether it can emit out-of-band observations)

The hub returns a **provider token**:

- `provider_token: str` — 24-char hex (`secrets.token_hex(12)`)

The provider token is then attached to any provider-originating calls back into the hub (e.g., posting a Delta, requesting subscription changes). This is an identity and trust-boundary mechanism; it is not intended to be cryptographic security in hostile settings.

#### 4.3.2 Subscription patterns

Subscriptions are matched against `HubEvent.event_type` (and optionally other routing keys) using simple glob semantics.

Examples:
- `turn_received`
- `delta_merged`
- `Events.*` (all events)
- `turn_observation_recorded`

A subscription may also include routing hints via payload keys (implementation-defined). If you want to subscribe to events that reference a specific turn, use `token_id`-scoped routing (the hub already emits `token_id` on turn-scoped events); do **not** rely on raw text matching.

#### 4.3.3 Changing subscriptions at runtime

TTT supports dynamic subscription updates via a dedicated hub call:

- `TTT.take_turn(ChangeSubscriptionsEvent(...))`

Payload shape (conceptual):
- `purpose_id: str`
- `provider_token: str`
- `delete_subs: list[str]` (optional)
- `add_subs: list[str]` (optional)

This call is only accepted if `provider_token` matches the currently registered token for `purpose_id`. The hub applies the update atomically for that provider.

> Note: the strings inside `add_subs` / `delete_subs` are subscription patterns (e.g., `Events.*`), not turn identifiers. If you need turn scoping, the hub should filter/route based on the event’s `token_id` (CTO token_id) or a separate explicit filter mechanism.

#### 4.3.4 Provider identity in events

Provider identity is carried as the **provider namespace** (`purpose_id`) inside:
- `Delta.provider`
- `Observation.owner`
- and, when needed, in `HubEvent.payload["provider"]`

The **provider token** is not intended to be written into every HubEvent payload; it is used to authenticate provider-originating requests to the hub.


---

## 5. Data Model

### 5.1 CTO — Canonical Turn Object

The CTO is the stable per-turn state container. It has a minimal identity surface plus accumulating metadata.

```python
@dataclass
class CTO:
    token_id:     str                     # 24-char hex; generated by hub
    timestamp:    float                   # unix epoch; hub sets if None
    text:         str                     # raw turn text (verbatim)
    role:         str                     # participant role label
    observations: dict[str, Observation]  = field(default_factory=dict)
    ext:          dict[str, Any]          = field(default_factory=dict)
```

- `observations` is for **structured, attributable annotations** that warrant an `Observation` wrapper.
- `ext` is for **lightweight provider metadata** (namespaced by provider) that other providers should treat as opaque unless explicitly shared.

### 5.2 Observation — attributable annotation unit

```python
@dataclass
class Observation:
    owner:  str   # provider namespace (e.g. "ue_detector")
    shared: bool  # True => readable by other providers; hub enforces immutability
    value:  Any   # JSON-safe provider-defined content
```

Semantics:
- **Shared observations** are *write-once* after first creation (hub enforces).
- **Owned/private observations** may be updated by the owning provider only (hub enforces).
- Provenance is still primarily a query over the event stream; the `owner/shared` fields support correctness and enforcement at write time.

### 5.3 Delta — provider mutation record

Providers report work via a Delta, which the hub can merge into the CTO and record in the event stream.

```python
@dataclass
class Delta:
    source_token_id: str          # CTO token_id the delta was derived from
    provider:        str          # provider namespace
    kind:            str          # provider-defined (e.g. "observation_added")
    payload:         dict[str,Any]# JSON-safe; convention: includes _schema and _v
    timestamp:       float        # unix epoch at delta creation
```

Delta merge policy is now expressed in hub logic rather than baked into a two-bucket `purpose_data/shared_data` structure. Common patterns:
- add/update `cto.observations[key] = Observation(...)`
- append-only “lists of contributions” can live either:
  - as a single shared Observation holding a list, or
  - as multiple Observations under distinct keys (depending on how you want to query)

### 5.4 DAGNode status machine (eligibility)

DAG nodes follow an explicit state machine:

`waiting → eligible → dispatched → resolved`

Eligibility checks must reflect `status == eligible` (hub-driven transitions).

---

## 6. TTT Internals

### 6.1 Subscription model — Switch with wildcard support

TTT is a **switch**: subscribers declare which event types and/or purpose_ids
they care about at registration time. TTT only forwards events to subscribers
whose declared interests match.

Wildcard subscriptions: `"*"` matches everything. `"turn_*"` matches all
turn lifecycle events. `"purpose_*"` matches all Purpose events.

TRTPurpose declares `subscriptions: ["*"]` — it receives all events
regardless of type or purpose_id.

`private=True` means TTT does not forward `purpose_resolved` to other
subscribers. TRTPurpose still receives it regardless of privacy setting.

### 6.2 Authentication / trust boundary (v0.6)

TTT assumes the hub is the **authority** for lifecycle events and state mutation. Providers/Purposes are *extensions* that can compute and propose changes (Deltas) but do not directly mutate shared state without hub mediation.

- Providers register via `TTT.register(purpose_id, subscriptions)` and receive a `provider_token` (`secrets.token_hex(12)`).
- Any provider-originating request (posting a Delta, requesting subscription changes) must include `purpose_id` + `provider_token`.
- The hub validates the token against its registry before accepting the request.

This mechanism is primarily for correctness and accidental misuse prevention (e.g., preventing a misconfigured provider from impersonating another). If you need a hostile-environment security model, treat this as scaffolding and add cryptographic authentication at the transport layer.


### 6.3 DAG execution

Purposes declare `depends_on: list[str]` in their `register` payload. TTT
maintains a per-turn resolution graph and dispatches Purposes as dependencies
are satisfied.

```
Turn arrives →
    embed (depends_on=[])             → dispatched immediately
    ca    (depends_on=[])             → dispatched immediately
    tm    (depends_on=["embed","ca"]) → waiting

embed resolves → tm still waiting for ca
ca resolves    → tm now eligible → dispatched
tm resolves    → DAG exhausted → turn_processing_complete
```

Independent Purposes run concurrently via `asyncio.gather`. Dependent
Purposes await their prerequisites.

### 6.4 Utilities — `ttt.utils`

```python
# Event stream reconstruction
def apply_delta(cto: CTO, delta: Delta, purpose_id: str) -> CTO: ...
def reconstruct(turn_id: str, events: list[HubEvent]) -> CTO: ...

# Shared namespace resolution
def resolve_shared(
    namespace: str,
    events: list[HubEvent],
    resolver: Callable[[list], Any]
) -> Any: ...

# Provenance formatting
def format_provenance(event: HubEvent) -> dict: ...
# Returns a flat, serializable dict of provenance-relevant fields
# for a single event. Callers serialize to JSON or log string as needed.
# Example output:
# {
#   "event_type": "purpose_resolved",
#   "event_id":   "a3f7...",
#   "timestamp":  1234567890.123,
#   "turn_id":    "t_001",
#   "purpose_id": "ca",
#   "purpose_name": "Conversation Analysis Annotator",
#   "entries_added": 2,
#   "shared_keys_updated": []
# }
```

`format_provenance` takes one event and returns a flat dict. It knows which
fields are meaningful for provenance across event types and normalizes them
into a consistent shape. Backends call it when writing log entries. Calling
code can call it directly.

---

## 7. TurnReTurn and TRTPurpose

**TurnReTurn** is the persistence, retrieval, formatting, and output product.
It is the brand and the system.

**TRTPurpose** is TurnReTurn's TTT integration point — a `PurposeProtocol`
implementation that plugs into the DAG and feeds TurnReTurn's Stores.
Someone who wants TurnReTurn's persistence features but has their own event
infrastructure can use TurnReTurn without TRTPurpose.

```python
class TRTPurpose:
    purpose_id = "trt"
    purpose_name = "TurnReTurn Persistence"
    # registered with: private=True, depends_on=[], subscriptions=["*"]

    def register_store(self, store: StoreProtocol) -> None: ...
    async def take_turn(self, event: HubEvent) -> None: ...
```

TRTPurpose is also the host for query views — since it holds the durable
event stream, provenance, session replay, and Purpose audit are naturally
expressed as queries against it.

```python
# Query views (available when a queryable Store is registered)
def provenance(self, turn_id: str) -> list[dict]: ...
def session_replay(self, session_id: str) -> list[HubEvent]: ...
def purpose_audit(self, session_id: str) -> list[dict]: ...
```

### 7.1 Store and Backend layering

A **Store** is the logical persistence target. A **Backend** is the specific
driver implementing a Store. This mirrors SQLAlchemy's dialect pattern.

```
TurnReTurn
    └── TRTPurpose
    └── Stores
          ├── FileStore
          │     ├── JSONLBackend
          │     ├── JSONBackend
          │     └── PlainTextBackend
          ├── MemoryStore
          │     └── MessageDictBackend
          └── SQLStore
                ├── SQLiteBackend
                └── PostgresBackend
```

Multiple Stores can be registered simultaneously. TRTPurpose fans out to all
of them on each event.

---

## 8. Package Structure

```
ttt/                          # pip install ttt
    core/
        cto.py                # CTO, Delta
        events.py             # HubEvent, well-known event_type constants
        protocols.py          # TurnTakerProtocol, PurposeProtocol,
                              # StoreProtocol
        hub.py                # TTT hub: DAG resolver, switch, token auth
        utils.py              # apply_delta, reconstruct, resolve_shared,
                              # format_provenance

trt/                          # pip install ttt[persist]
    purpose.py                # TRTPurpose
    stores/
        file_store.py         # FileStore
        memory_store.py       # MemoryStore
        backends/
            jsonl.py          # JSONLBackend (under FileStore)
            json_.py          # JSONBackend (under FileStore)
            plaintext.py      # PlainTextBackend (under FileStore)
            messagedict.py    # MessageDictBackend (under MemoryStore)

trt_sql/                      # pip install ttt[persist-sql]
    stores/
        sql_store.py          # SQLStore
        backends/
            sqlite.py         # SQLiteBackend
            postgres.py       # PostgresBackend
```

---

## 9. Adjacency Integration

Adjacency is both **upstream** and **downstream** of TTT:

- **Upstream**: Adjacency's session runner constructs `turn_observed` events
  and calls `ttt.take_turn(...)` to feed turns into the system. Adjacency is
  the source of the raw turn data that becomes a CTO.
- **Downstream**: Adjacency-specific Purposes (CA annotation, trace mutation
  detection, reviewer scoring) register with TTT and receive `purpose_resolved`
  events for the namespaces they declared interest in.
- **Feedback**: Purposes may emit `speaker_feedback` events that Adjacency's
  session runner receives and acts on — e.g. a terminology drift signal from
  a StashKit-backed Purpose.

Adjacency's existing session log (JSONL) becomes a TurnReTurn FileStore
output rather than a separately managed artifact. The log format is preserved;
the machinery producing it is replaced by TRTPurpose + JSONLBackend.

---

## 10. Installation

```
pip install ttt                  # core only — no storage dependencies
pip install ttt[persist]         # + TurnReTurn with FileStore, MemoryStore
pip install ttt[persist-sql]     # + SQLStore with SQLite and Postgres backends
```

---

## 11. What TTT Is Not

- Not an API gateway or HTTP proxy
- Not an LLM alignment system
- Not an observability platform (though it can feed one via a Store)
- Not a replacement for OpenTelemetry, Langfuse, or Phoenix — it can emit
  to any of these via a Store or subscriber
- Not an actor framework — it uses actor model concepts implemented directly
  on asyncio

---

## Appendix A — Reference Material from Earlier Document

The following sections from *Alignment Middleware for Human–LLM Dialogue*
(March 2026) remain useful as reference for Purpose implementations that
would run on top of TTT. They are preserved here without modification.

### A.1 Trace Candidate Schema

Relevant to a TraceMutation Purpose implementation.

```yaml
trace_candidate:
  trace_id: ...
  span: {message_id, char_start, char_end}
  type: [decision|constraint|definition|plan|ownership|other]
  owner: [user|model|joint|unknown]
  text: ...
  normalized: ...
  timestamp: ...
  confidence: 0..1
```

### A.2 Alignment Signals (for an Alignment Purpose)

1. **User-constraint preservation score** — compare embeddings of current
   model response vs nearest constraint traces; low similarity + high
   confidence restatement => risk.
2. **Negation risk flag (UE-leaning)** — detect negation operators in user
   traces; if model restates without negation or with polarity flip, raise
   risk.
3. **Provenance compression score (GD-leaning)** — track pronoun/possessive
   shifts around accountability moments ("we/our" → "you/your").
4. **Commitment continuity score** — compare "what we decided" summaries
   across time; detect discontinuous jumps.

### A.3 Mutation Candidate Event Schema (for a TraceMutation Purpose)

```yaml
mutation_candidate:
  kind: [UE|GD|unknown]
  source_trace_id: ...
  degenerate_trace_span: ...
  evidence:
    - similarity_drop: ...
    - contradiction_score: ...
    - provenance_shift: ...
  severity: [low|med|high]
  proposed_action: ...
```

### A.4 DecisionCard / Provenance Accumulator

A DecisionCard Purpose would separate (1) append-only provenance from
(2) replaceable resolved snapshots, supporting deterministic re-resolution
when evidence evolves.

Key design invariants:
- CTO is verbatim-first and immutable (enforced by TTT core)
- Provenance and annotations are append-only and span-referenced
- "Current state" is always a materialized view with explicit `resolver_id`
  and `evidence_bundle_id`, so it can be re-resolved deterministically

### A.5 Alignment Snapshot Contents (for an Alignment Purpose)

- `snapshot_id`, `turn_id`, `decision_ids` touched
- `anchor_trace_ids` (constraints/definitions/commitments)
- `alignment_scores` (per-signal + composite)
- `state_summary_text` (compact) + `state_summary_embedding`
- `recent_drift_delta` (change from last snapshot)

### A.6 LLMZ Guidance Packet (for a Guidance Purpose)

```
[LLMZ]
GOAL: preserve shared-record integrity; avoid unilateral restatement of
      user constraints.
ANCHORS:
- (trace_id=...) "constraint text" [MUST-PRESERVE]
CHECKS:
- Before proposing plan, restate anchored clauses verbatim.
- Do not negate deferred commitments.
REPAIR:
- If conflict detected, ask one clarification Q; otherwise silently align.
[/LLMZ]
```

### A.7 Integration Roadmap (adapted)

**Phase 1 — Working pipe**
- TTT core + TRTPurpose + JSONLBackend
- Adjacency session runner emitting `turn_observed` events
- DAG execution with zero-dependency Purposes

**Phase 2 — Trace-aware**
- TraceMutation Purpose (heuristic first pass)
- Embedding Purpose (SBERT + FAISS in-process)
- CA annotation Purpose
- DecisionCard Purpose (append-only evidence accumulation)
- Shared namespace usage for open CA schema contributions

**Phase 3 — Guided**
- Alignment signal Purpose
- `speaker_feedback` → Adjacency session runner loop
- LLMZ packet generation Purpose
- Offline replay and heavier analysis passes
- Resolver Purposes for shared namespace canonicalization

---

*TTT Architecture v0.4 — March 2026*
*Drafted from design session. Companion document: Adjacency ADR v1.0.*

*v0.4 changes from v0.3:*
- *`ttt.register()` as convenience wrapper clarified — `take_turn` is the*
  *one true path; `register()` constructs and dispatches internally*
- *`subscription_update` event added for mid-session subscription changes*
- *`purpose_id` removed from `purpose_complete` payload — resolved from*
  *token by TTT; prevents spoofing*
- *`format_provenance(event) -> dict` added to `ttt.utils`; per-event,*
  *flat, serializable, caller serializes to JSON or log string*
- *`provenance()` list traversal utility removed from `ttt.utils` —*
  *provenance is a TurnReTurn query view, not a core utility*
- *Design principles updated: `take_turn` is the one true path*

---

# Addendum E — Postgres Substrate (Authoritative Log + Projections)

This addendum specifies a **minimal Postgres-first** persistence layout consistent with the core invariants:

- **Append-only** authoritative record (no overwrites; replayable)
- **Purpose-run tokens** (`purpose_token`) are run-scoped and can span many turns/sessions
- **CTO is per-turn** and identified by `(conversation_id, turn_index)` (or an optional `turn_id`)
- **Extensibility** is achieved with JSONB payloads + selective indexing (no schema churn)

## E.1 Identity model

### E.1.1 Conversation + Turn identity (recommended)

- `conversation_id` — UUID (or 64–96-bit hex string) identifying a conversation/session grouping
- `turn_index` — integer, monotonically increasing within `conversation_id`

Primary key:
- `(conversation_id, turn_index)`

Optional convenience:
- `turn_uid` computed as `conversation_id || ':' || turn_index`

### E.1.2 Purpose-run identity

- `purpose_id` — stable identifier for the Purpose type (e.g., `"CA"`, `"embeddingizer"`, `"TRTPurpose"`)
- `purpose_token` — 24-char hex string returned by `TTT.register()` and used to authenticate Purpose-originating requests

A single `purpose_token` may cover:
- many turns,
- and multiple conversation sessions,
depending on how you scope “run.”

## E.2 Tables (minimal viable)

### E.2.1 `hub_events` — authoritative append-only log

The event stream is the source of truth. Everything else can be derived.

```sql
create table hub_events (
  event_id        bigserial primary key,
  event_time      timestamptz not null default now(),

  -- Routing / grouping
  conversation_id uuid null,
  turn_index      int null,
  purpose_id      text null,

  -- Core event type (enum or text)
  event_type      text not null,

  -- JSONB payload for event-specific content
  payload         jsonb not null,

  -- Integrity
  payload_hash    bytea null
);
```

Notes:
- `conversation_id`/`turn_index` are nullable to support non-turn-scoped events (e.g., `purpose_registered`, `subscriptions_changed`).
- `payload` is JSONB and should include `_schema` and `_v` when the event’s internal structure matters.
- You can add `purpose_token` to `payload` for requests, but **do not** store it on accepted events unless you need an audit trail; typically you store only `purpose_id` and keep `purpose_token` in the registry table.

### E.2.2 `ctos` — per-turn state snapshot (optional but practical)

This is a materialized convenience table. It is allowed to be “latest view” because the authoritative record is still `hub_events`.

```sql
create table ctos (
  conversation_id uuid not null,
  turn_index      int not null,

  -- stable per-turn fields
  created_at      timestamptz not null default now(),
  speaker_role    text not null,         -- "human" | "model" | "system" (or richer labels)
  text            text not null,         -- raw turn text (verbatim)
  text_hash       bytea null,

  -- observations are append-only lists per key
  observations    jsonb not null default '{}'::jsonb,

  primary key (conversation_id, turn_index)
);
```

Observations encoding:
- `observations` is a JSON object keyed by observation key; each value is a JSON array of Observation objects:
  - `[{ "owner": "...", "shared": true, "value": ... }, ...]`

This matches the “every value is a list; hub appends” invariant.

### E.2.3 `purpose_runs` — registry for Purpose tokens and subscriptions

```sql
create table purpose_runs (
  purpose_id      text not null,
  purpose_token   char(24) not null,

  -- run scope / lifecycle
  created_at      timestamptz not null default now(),
  last_seen_at    timestamptz null,
  is_active       boolean not null default true,

  -- subscriptions expressed as patterns; stored as jsonb array of strings
  subscriptions   jsonb not null default '[]'::jsonb,

  primary key (purpose_id, purpose_token)
);
```

Notes:
- This table is the trust boundary: hub validates `(purpose_id, purpose_token)` for Purpose-originating requests.
- If you later want “one active token per purpose_id,” enforce via a partial unique index on `purpose_id where is_active`.

## E.3 Indexes (day 1)

For replay and common queries:

```sql
create index hub_events_conv_turn_time
  on hub_events (conversation_id, turn_index, event_time);

create index hub_events_type_time
  on hub_events (event_type, event_time);

-- If you frequently query by purpose_id (e.g., debugging a Purpose)
create index hub_events_purpose_time
  on hub_events (purpose_id, event_time);
```

For JSONB filtering (only add when needed):

```sql
-- Example: find events whose payload contains a key/value pattern
create index hub_events_payload_gin
  on hub_events using gin (payload);
```

For CTO retrieval:

```sql
create index ctos_conv_time
  on ctos (conversation_id, created_at);
```

## E.4 Replay model

Replay is a query over `hub_events`:

- “Replay a conversation”: `where conversation_id = ... order by turn_index, event_time, event_id`
- “Replay a turn”: `where conversation_id = ... and turn_index = ... order by event_time, event_id`

Because the authoritative stream is append-only, strict ordering requirements are minimal. Recommended tie-break:
- `event_time`, then `event_id` (monotone).

## E.5 Projections (derived consumers)

Treat everything beyond the core as **derived projections**:

- DecisionCard materialization (from DecisionMove events)
- Alignment snapshots
- Trace-probe / adjacency annotations
- Search indices

Each projection:
- reads from `hub_events` (and optionally `ctos`),
- writes to its own tables/materialized views,
- can be re-run as rules evolve.

## E.6 When to add a vector index (optional)

When you need semantic retrieval at scale:
- store embeddings out-of-row (vector DB or Postgres pgvector),
- store only embedding references in event payloads and/or CTO observations.

If you want to stay Postgres-only, pgvector is a reasonable next step; otherwise keep the vector index as a separate projection.

