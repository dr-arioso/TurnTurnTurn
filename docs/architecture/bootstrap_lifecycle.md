# Bootstrap and Lifecycle

## Purpose

This document defines the intended mesh bootstrap and session lifecycle model for
**TurnTurnTurn (TTT)**.

It is an architecture document, not a claim that every detail is already
implemented exactly as described. Its purpose is to make the target invariants
explicit so code, docs, and downstream packages can converge on the same model.

## Scope

This document belongs to **TTT**, not `adjacency` or `traceprobe`.

TTT owns:

- mesh bootstrap order
- Purpose admission and activation
- persistence prerequisites
- session ownership rules
- session shutdown sequencing
- lifecycle event routing rules

Adjacency and TraceProbe should only depend on the public consequences of those
rules. They should not need to re-document or re-implement mesh lifecycle.

## Core invariants

The intended model is:

1. The hub owns canonical CTO state and routing policy.
2. Purposes author mesh events.
3. Persist Purposes persist the events they emit.
4. At least one Persist Purpose must be active before normal operation begins.
5. The session owner is a registered Purpose, not ambient calling code.
6. Only registered Purposes may call `start_turn()`.
7. The Purpose that instantiates a session's first turn becomes that session's owner.
8. Session shutdown proceeds through mesh events, not direct persistence writes by the hub.

## Roles

### Hub

The hub is authoritative for:

- binding Purposes into the mesh
- deciding which Purposes are currently admitted
- creating CTOs
- merging Deltas
- routing events
- enforcing session-owner-only actions

The hub is **not** the persistence layer. It emits events and updates canonical
CTO state; it does not itself persist arbitrary event history.

### Persist Purpose

A Persist Purpose is a first-class Purpose that also persists the events it
emits. Persist Purposes are special in load order and shutdown order, but they
are still mesh participants.

Persist Purposes are expected to:

- join the mesh first
- remain present until shutdown is complete
- emit and persist `session_started`
- emit and persist `session_completed`
- persist their own `purpose_started` and `purpose_completed`

The durability flag (`is_durable`) is the primary policy hook for distinguishing
real persistence from transient buffering or test-only persistence.

### Session Owner Purpose

The session owner is the explicit Purpose responsible for instantiating a
session. This is not ambient caller privilege.

A session owner may:

- trigger the first `start_turn()` for a new session
- request session shutdown when appropriate

The current ownership rule is intentionally simple:

- the registered Purpose that creates the first turn for a session is the owner

This keeps authority concrete and attributable in the mesh.

### Other Purposes

All other Purposes are ordinary domain or infrastructure actors. They should not
need bespoke knowledge of bootstrap internals. Their lifecycle contract is:

- join after the required bootstrap participants are active
- emit `purpose_started` for provenance
- do domain work
- respond to `session_closing`
- emit `purpose_completed` when they are clear

## Bootstrap sequence

The intended bootstrap sequence is synchronous from the caller's point of view.

When startup returns, the mesh should already be in a normal operating state.

### Required ordering

1. Calling code constructs the selected Persist Purpose configuration.
2. Calling code constructs the session-owner Purpose.
3. Calling code asks the hub to start with those required participants.
4. The hub binds Persist first.
5. Persist emits and persists `session_started`.
6. Persist emits and persists `purpose_started` for itself.
7. The hub binds the session-owner Purpose.
8. The session-owner emits `purpose_started`.
9. The hub admits any additional queued registrations.
10. Normal operation begins.

### Why bootstrap is synchronous

Synchronous bootstrap keeps lifecycle complexity inside TTT instead of pushing it
out into every consumer.

The desired contract is simple:

- before startup returns, the mesh is not ready
- after startup returns, the mesh is ready

That is preferable to requiring session-owner Purposes or outside calling code to
queue work speculatively before they are on the mesh.

## Registration semantics

Registration and provenance are separate concerns.

The preferred model is:

- registration is immediate when the hub admits a Purpose
- `purpose_started` is a provenance and informational event, not a handshake
  required to complete admission

This keeps registration simple while still recording lifecycle facts on the mesh.

## Persistence policy

TTT should require an explicit Persist Purpose at startup.

### Durable and transient persistence

`is_durable=True` means the persistence backend is intended to survive process
termination and act as real provenance storage.

`is_durable=False` means the backend is transient, for example:

- in-memory persistence for tests
- a temporary bootstrap buffer
- development-only sinks

The durability flag should drive startup policy.

Examples:

- production mode: require at least one durable Persist Purpose
- test mode: allow transient-only persistence
- staged bootstrap: allow a transient bootstrap buffer before a durable sink is
  available

## Session lifecycle

### Session start

`session_started` is a persistence/lifecycle fact. It is emitted by a Persist
Purpose as part of bootstrap.

Calling code and ordinary domain purposes should not be responsible for authoring
that event.

### Session execution

Once bootstrap is complete, the caller can "get on with it":

- register additional Purposes
- load domain configuration
- trigger the owner's first `start_turn()`

This is ordinary orchestration, not lifecycle bootstrap.

### Session close

The intended close sequence is:

1. The session owner requests session end.
2. The hub emits `session_closing`.
3. Non-persist Purposes finish outstanding work.
4. Those Purposes emit `purpose_completed`.
5. Once only Persist remains, the hub emits an all-clear event.
6. Persist emits and persists `session_completed`.
7. The hub closes.

This preserves the same structural principle as startup:

- Persist is first onto the mesh
- Persist is last off the mesh

## Event authorship rules

The intended direction is:

- domain events are purpose-authored
- `purpose_started` and `purpose_completed` are purpose-authored
- `session_started` and `session_completed` are Persist-authored
- the hub may emit coordination events such as `session_closing`
- the hub should not directly persist event history outside the mesh protocol

The important rule is consistency: lifecycle facts should appear on the same
provenance surface as domain facts rather than being smuggled around the mesh.

## Downstream impact

### Adjacency

Adjacency should not own mesh lifecycle policy.

Adjacency should only need to know:

- how to start a session once its owner Purpose is registered
- how to emit domain events
- how to react to session shutdown through the generic Purpose contract

### TraceProbe

TraceProbe should remain a domain layer atop Adjacency and should not absorb TTT
bootstrap responsibilities.

## Documentation guidance

This architecture should be reflected in two places:

- code-level docstrings near bootstrap and lifecycle APIs
- explicit MkDocs architecture pages such as this one

The most important thing to keep stable in docs is the invariant set. Narrative
descriptions can evolve, but the invariants should remain easy to find and easy
to test against code.

