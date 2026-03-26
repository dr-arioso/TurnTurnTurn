# Architecture

This directory contains the current architecture documents for **TurnTurnTurn**.

## Canonical docs

- [Bootstrap and Lifecycle](bootstrap_lifecycle.md)
  Mesh bootstrap, persistence prerequisites, session ownership, and shutdown.
- [Core Architecture](core_architecture.md)
  The substrate model: CTOs, Purposes, Deltas, event routing, and scope.

## Documentation rule

These files are the canonical architecture pages for TTT.

- Use `bootstrap_lifecycle.md` for mesh/session lifecycle invariants.
- Use `core_architecture.md` for the broader substrate model.
- Use docstrings for code-local API contracts.

Do not create new architecture notes beside these without a clear reason. Fold
active design changes into the canonical docs instead of accumulating addenda.
