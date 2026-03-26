# TurnTurnTurn

**TurnTurnTurn (TTT)** is a lightweight hub runtime for routing, enriching, and
preserving provenance over sequential work items.

TTT is built around a single canonical object:

- **CTO** — Canonical Turn Object

TTT does **not** define domain semantics. It provides:

- authoritative CTO creation via `start_turn()`
- hub-mediated Delta merge
- typed HubEvents
- Purpose registration and dispatch
- replayable provenance through the event stream

The canonical example profile is **`conversation`**, but TTT is **profile-based**,
not hard-coded to speaker/text semantics.

## Core concepts

| Concept | Description |
|---------|-------------|
| **TTT** | The hub runtime. Authoritative for CTO creation, Delta merge, and event emission. |
| **CTO** | Canonical Turn Object. The hub-authoritative work item. Frozen; replaced on each merge. |
| **CTOIndex** | Lightweight routing reference carried in event payloads. Purposes call `ttt.librarian.get_cto()` for full state. |
| **BasePurpose** | Abstract base class for Purposes. Enforces hub token validation. Subclasses implement `_handle_event()`. |
| **Purpose** | A registered agenda-bearing actor that receives HubEvents and may propose Deltas. |
| **Delta** | A purpose-proposed change, merged authoritatively by TTT into the Purpose's observation namespace. |
| **HubEvent** | An authoritative event emitted by TTT. Per-recipient envelope with hub token. The primary provenance surface. |

## Start here

- [Architecture Overview](architecture/index.md)
  Entry point for TTT architecture docs.
- [Bootstrap and Lifecycle](architecture/bootstrap_lifecycle.md)
  The authoritative mesh/session lifecycle architecture.
- [Core Architecture](architecture/core_architecture.md)
  The substrate model: CTOs, Purposes, Deltas, routing, and scope.
- [Hub API](api/hub.md)
  Current public hub API surface.
- [Events API](api/events.md)
  Event taxonomy and payload reference.
- [Developer Guide](dev-guide.md)
  Local development, docs, and verification workflow.

## Status

This project is in active architectural development. The core object model,
hub semantics, profile system, and Purpose dispatch are stable. The DAG
eligibility layer and parts of the bootstrap/lifecycle model are still evolving.
