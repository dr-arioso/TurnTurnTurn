# Core Architecture

## Purpose

This document describes the core architecture of **TurnTurnTurn (TTT)** as a
general-purpose provenance substrate.

It is the canonical architecture overview for TTT. Lifecycle-specific rules
such as bootstrap order, persistence prerequisites, session ownership, and
shutdown sequencing belong in [Bootstrap and Lifecycle](bootstrap_lifecycle.md).

## Positioning

TTT is a provenance-first hub for processing sequential work items through a
mesh of registered Purposes.

TTT is built around one canonical object:

- **CTO** — Canonical Turn Object

TTT does **not** define domain semantics. It provides:

- authoritative CTO creation
- hub-mediated Delta merge
- authenticated Purpose registration and routing
- replayable event provenance
- profile-based content handling

The `conversation` profile is an example, not a direction.

## Core invariants

- Only TTT may create CTOs.
- Only TTT may make canonical state changes.
- Purposes propose; they do not commit.
- Canonical observation history is append-only.
- Event payloads carry references rather than full canonical state snapshots.
- Every accepted event that matters for provenance goes through the mesh.
- TTT remains domain-agnostic; workflow or study semantics belong upstream.

## Core objects

### TTT

The hub runtime.

TTT is authoritative for:

- CTO creation
- Delta validation and merge
- Purpose registration and authenticated routing
- canonical dispatch order
- librarian-backed CTO reads

TTT is not the workflow brain and is not the domain layer.

### CTO

The **Canonical Turn Object** is the authoritative work item.

A CTO is introduced into the mesh either by direct creation with
`start_turn()` or by persistence-backed import via `request_cto` ->
`cto_imported` -> `cto_started`. Once live, it is never mutated directly and
is replaced on every accepted merge. Its stable responsibilities are:

- carry profile identity
- carry profile-conformant content
- carry additive observations
- carry session and turn identity
- carry provenance linkage through `last_event_id`

CTO semantics are specialized by content profile, not by inventing a different
core object type for each consuming framework.

### CTOIndex

`CTOIndex` is the lightweight routing/reference object that travels on the
event mesh. It exists so Purposes can make dispatch decisions and record
provenance without requiring full CTO snapshots on the bus.

Purposes that need full state call `ttt.librarian.get_cto(turn_id)`.

### Purpose

A Purpose is a registered mesh-visible actor.

Purposes:

- receive hub-authored events
- may emit purpose-authored events through the hub
- may propose Deltas
- own their own local state and bounded logic

Ambient calling code is not a mesh actor. If code must participate in session
or mesh behavior, it should do so through an explicit Purpose.

### Delta

A Delta is a purpose-authored proposal for additive observation changes.

The hub validates the proposal and, if accepted, merges it into the submitting
Purpose's namespace. Purposes do not write canonical state directly.

## Profiles

TTT is **profile-based**.

The hub owns the substrate and the canonical carrier object; profile families
specialize the content shape. This keeps the substrate reusable across very
different workflows while allowing upstream frameworks to define shared profile
conventions.

## Layer boundaries

TTT should own:

- provenance substrate behavior
- canonical CTO state
- Purpose registration and routing
- additive merge semantics
- replay and reconstruction support

TTT should not own:

- elicitation semantics
- protocol ladders
- study roles as domain concepts
- prompt interpolation
- exhibit semantics
- TraceProbe-specific ontology

Those belong in consuming frameworks such as Adjacency or TraceProbe.

## Relationship to higher layers

The intended stack is:

```text
TTT  ->  Adjacency  ->  TraceProbe
```

- **TTT** is the canonical substrate.
- **Adjacency** is the reusable interaction / language-study framework.
- **TraceProbe** is a domain specialization.

The healthy separation is:

- TTT owns provenance and canonical mesh behavior
- Adjacency owns reusable workflow semantics
- TraceProbe owns domain-specific semantics

## Change policy

When architecture changes:

- update this file if the substrate model or layer boundaries change
- update `bootstrap_lifecycle.md` if the mesh/session lifecycle changes
- update docstrings if the API contract changes

Do not create versioned or addendum architecture files for active design
changes unless there is a specific temporary reason.
