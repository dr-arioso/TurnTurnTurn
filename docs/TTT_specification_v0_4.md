TTT Specification
=====================


Overview
--------
TurnTurnTurn (TTT) is an event-driven, hub-and-purpose framework for processing conversational "turns". The hub is the authoritative component that merges producer-suggested changes (Deltas) into canonical per-turn state (CTO). Purposes are first-class peers that subscribe to events, propose Deltas, and consume HubEvents routed by the DAG router.

Goals
-----
- Provide a deterministic, auditable core for turn processing.
- Keep core semantics small: append-only history, hub-authoritative merges, lightweight datamodels.
- Enable flexible topologies (fan-out, fan-in, dynamic subscriptions) via a DAG router.
- Support pluggable persistence and offline reconstruction from events.

Conventions
-----------
- **Canonical identifiers:** `turn_id` is the only valid turn identity key.
- **Subscriptions:** match on `HubEvent.event_type` patterns (routing), then apply optional attribute filters (filtering).
- `SubscriptionLike` (v0): either a string `event_type` pattern, or an object with:
  - `event_type: str` (pattern; may be "*")
  - optional filters such as `turn_id: str` and `purpose_id: str`
  - hubs MUST ignore unknown keys in subscription objects.
- All event payloads follow `_schema` (str) and `_v` (int) to allow evolution.
- Identifiers:
  - `turn_id`: CTO identity (24 hex chars via `secrets.token_hex(12)`).
  - `purpose_id`: stable namespace for a Purpose type (string, e.g., "ca", "embed").
  - `purpose_token` (optional): registration token used to authenticate purpose-originated requests.

Data Model
----------
CTO (Canonical Turn Object)
- Fields (minimal):
  - `turn_id: str`
  - `timestamp: float`
  - `text: str`
  - `role: str`
  - `observations: dict[str, Any]` — values are either a single Observation value (owned namespace) or a list (shared namespace).

Observation
- Lightweight wrapper describing attribution and storage semantics.
- Fields:
  - `owner: str` (purpose_id)
  - `shared: bool` — `False` => owned namespace; `True` => shared namespace (list semantics)
  - `value: Any` — semantic meaning depends on `_schema`.

Delta
- Producers (Purposes) create Deltas describing intended mutations.
- Fields:
  - `source_turn_id: str`
  - `purpose_id: str`
  - `invocation_id: str | None` (hub-generated for dispatch correlation)
  - `kind: str`
  - `payload: dict[str, Any]` (must include `_schema` and `_v` where applicable)
  - `timestamp: float`
- Important: Deltas are proposals. They do not themselves mutate `cto.observations`; the hub must apply/merge them.

Purpose
- Represents an actor that subscribes to HubEvents and emits Deltas.
- Registration includes `purpose_id`, `subscriptions`, and optional `capabilities`.

HubEvent
- Emitted by the hub for lifecycle transitions and important actions.
- Fields include `event_id`, `event_type` (EventType), `turn_id | None`, `payload`, `timestamp`.

Core Semantics
--------------
Hub Authority
- The hub is the only component permitted to modify `cto.observations` and `ctos` state.
- Purposes only submit Deltas describing changes; the hub validates and applies them.

Append-only
- All applied contributions are recorded and preserved. The hub never silently discards prior contributions when merging.
- Owned namespaces: the hub records contributions associated with the owning `purpose_id`. Other purposes may read these entries but cannot propose writes to them.
- Shared namespaces: the hub enforces that the stored value is a list; every contribution is appended to the list.

Merge Rules (hub)
- Deterministic, documented behavior implemented by the hub. Example rules:
  - Owned-namespace contribution: hub appends an Observation entry under `observations[purpose_id]`, preserving prior contributions in event history (if desired, the hub may maintain internal per-purpose append history separate from `observations` value for compact read models).
  - Shared contribution: hub ensures `observations[shared_key]` is a list and appends; initializes a single-element list if first contribution.
  - Structured payloads: hub may call registered merge functions (pluggable) while preserving event history — these functions must be deterministic and designed to compose with append-only guarantees.
- Rejections: malformed Deltas, unauthorized writes (attempt to write to a different purpose's owned namespace), or invalid payloads are rejected with a HubEvent (failure) and logged.

Provenance
- The authoritative trail is the event stream (HubEvents and persisted Deltas). The `observations` dict is a denormalized view for convenient consumption; provenance must be reconstructed by querying the events.

DAG Router & Subscription Model
-------------------------------
- Purposes register interest declaratively (event types, purpose_ids, or schema patterns).
- The hub emits HubEvents after applying Deltas; the router matches events to subscribed Purposes and dispatches `Purpose` invocations.
- Subscription patterns support wildcards (`*`, `turn_*`, `purpose_*`) and schema filters. A minimal in-process dispatch mechanism will be provided initially; later this can become async or cross-process.

API Surface (sketch)
---------------------
Hub (in `src/turnturnturn/hub.py`)
- `class Hub:`
  - `add_cto(cto: CTO) -> None` — persist a new CTO in-memory or via storage.
  - `get_cto(turn_id: str) -> CTO | None`.
  - `submit_delta(delta: Delta) -> HubEvent` — validate, apply, persist, emit.
  - `apply_delta(cto: CTO, delta: Delta) -> list[HubEvent]` — apply one or more HubEvents as a result of merge.
  - `register_purpose(purpose_id: str, subscriptions: list[SubscriptionLike], token: str | None)`.
  - `list_events(turn_id: str) -> list[HubEvent]` — readback for provenance.

Router (in `src/turnturnturn/router.py`)
- `class Router:`
  - `register(purpose_id: str, callback: Callable[[HubEvent], None], subscriptions: list[SubscriptionLike])`
  - `dispatch(event: HubEvent) -> None` — route to matching callbacks.

Helpers
- `apply_shared_append(cto, key, value)`
- `apply_owned_contribution(cto, purpose_id, value)`
- `validate_delta(delta)`

Storage & Persistence
- v0: in-memory for rapid iteration, with an interface to swap in a durable store.
- Event store: append-only list; CTO snapshot store: compact view built from events.
- Provide utilities to replay events to reconstruct CTO state.

Security & Governance
---------------------
- Purposes authenticate with `purpose_token` during registration; hub validates tokens before accepting Deltas.
- Capabilities: registration may include capabilities (e.g., whether purpose can create certain schema types or publish to shared namespace). Hub enforces capabilities at write time.

Operational Concerns
--------------------
- Backpressure: router and hub must support throttling; Deltas may be queued for persistence and merging.
- Idempotency: Deltas should include stable identifiers where retries may occur; hub deduplicates on `invocation_id`/Delta id.
- Observability: hub emits diagnostic HubEvents for errors, rejections, and lifecycle transitions.

Testing
-------
- Unit tests for `apply_shared_append` and `apply_owned_contribution` covering append semantics, initialization, and invalid writes.
- Integration tests: submit sequences of Deltas and assert final CTO snapshot and event log content.

Appendix — Design Decisions
---------------------------
1. Hub-authoritative merges
   - Rationale: centralizes correctness (append-only invariants, provenance) and simplifies reasoning for Purpose authors.

2. Purposes-as-peers
   - Rationale: avoids rigid upstream/downstream hierarchy; supports dynamic composition, cross-cutting concerns, and runtime extensibility.

3. Append-only default
   - Rationale: preserves auditability and enables easy replay. Replacements can be modeled by append with a special `_schema` that marks a correction if needed.

4. `_schema` + `_v`
   - Rationale: explicit schema versioning avoids brittle implicit contracts and allows gradual evolution.

5. Start in‑memory, pluggable persistence
   - Rationale: accelerates iteration and tests; provides clear upgrade path for production stores.

Next steps (implementation roadmap)
-----------------------------------
1. Implement `src/turnturnturn/hub.py` with core APIs and in-memory stores (CTO map, event list).
2. Add `src/turnturnturn/router.py` with subscription registry and simple dispatch.
3. Add tests under `tests/` covering merge rules and end‑to‑end flow.
4. Provide an example script demonstrating `take_turn` → hub merge → HubEvent dispatch → purpose callback.






