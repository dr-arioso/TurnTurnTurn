# TurnTurnTurn — Agent Orientation

## What this is
TTT is a hub runtime built around the Canonical Turn Object (CTO). The hub is
the sole authority for CTO creation and canonical state. Processors (Purposes)
propose changes via Deltas; the hub validates and merges them. Nothing writes
to canonical state directly.

## Current status
- Core object model and hub semantics: stable
- DAG eligibility layer: not yet implemented
- Persistence: not yet implemented
- `ids.py`, `day.py`, `errors.py`: empty stubs, not yet implemented

## Key naming history
- `TurnSnargle` / `submit_snargle()` — retired; replaced by direct `start_turn()` on the hub
- `turn_received` — retired event name; canonical name is now `cto_created`
- `text` / `role` as CTO fields — retired; replaced by `content_profile` / `content`

If you see these names anywhere in the codebase, they are stragglers and should
be updated.

## Before you commit
```bash
pytest --cov=turnturnturn
pre-commit run --all-files   # ruff, black, isort, mypy --strict, interrogate
```

## Before you change a public interface
Read `docs/ttt_architecture_v0_15.md`. The principles in §2 are load-bearing —
especially "TTT is authoritative" and "append-only by default." Changes that
would require a Purpose to write canonical state directly are wrong by design,
not by accident.

## Do not
- Add domain semantics to the hub or CTO — `conversation` is an example profile,
  not evidence that TTT is a conversation library
- Implement the DAG layer speculatively — wait until Adjacency integration
  drives the requirements from real usage
- Rename things without updating the naming history section above