# TurnTurnTurn — Agent Orientation

## What this is

TTT is a hub runtime built around the Canonical Turn Object (CTO). The hub is
the sole authority for CTO creation and canonical state. Processors (Purposes)
propose changes via Deltas; the hub validates and merges them. Nothing writes
to canonical state directly.

## Current status

- Core object model and hub semantics: stable
- Profile system (Profile, ProfileRegistry, FieldSpec): stable
- DAG eligibility layer: not yet implemented (`dag.py` is a stub)
- Persistence: not yet implemented
- `ids.py`, `errors.py`: empty stubs, not yet implemented

## Key naming history

The following names are retired. If you see them anywhere in the codebase
they are stragglers and should be updated:

| Retired | Replacement |
|---------|-------------|
| `TurnSnargle` | — (concept removed; use `start_turn()` directly) |
| `submit_snargle()` | `ttt.start_turn()` |
| `turn_received` | `cto_created` |
| `content["speaker"]` | `content["speaker_id"]` |
| `CTO.speaker` | `CTO.speaker_id`, `CTO.speaker_role`, `CTO.speaker_label` |
| `validate_content_profile()` | `Profile.validate()` via `ProfileRegistry` |
| `apply_conversation_defaults()` | `Profile.apply_defaults()` via `ProfileRegistry` |
| `_speaker_registry` on hub | `_session_contexts` (opaque; profile-owned contents) |

## The invariant that matters most

**No profile-specific code in core modules.** `cto.py` and `hub.py` must
remain profile-agnostic. If you find yourself adding a branch, import, or
field that refers to "conversation", "speaker", or any other profile concept
in either of those files, stop. The profile system exists to prevent exactly
that. Add a `Profile` subclass or extend `FieldSpec` instead.

## How profiles work

Profiles are registered with `ProfileRegistry` (process-scoped class-level
registry). The hub looks up profiles at `start_turn()` time by string id.
The CTO carries only `{"id": ..., "version": ...}` — no object references.
`CTO.__getattr__` dispatches to `ProfileRegistry.resolve()` for attribute
access. The hub passes an opaque mutable `session_context` dict to
`Profile.apply_defaults()` — profiles own its contents entirely.

To add a new profile: construct a `Profile` with `FieldSpec` declarations,
call `TTT.register_profile()`. No core changes required. See CONTRIBUTING.md.

## Before you commit

```bash
pytest --cov=turnturnturn
pre-commit run --all-files   # ruff, black, isort, mypy --strict, interrogate
```

## Before you change a public interface

Read `docs/ttt_architecture_v0_15.md`. The principles in §2 are load-bearing.
Changes that would require a Purpose to write canonical state directly, or that
add domain semantics to the hub or CTO, are wrong by design, not by accident.

## Do not

- Add any profile-specific code to `cto.py` or `hub.py`
- Add domain semantics to the hub or CTO — `conversation` is an example profile,
  not evidence that TTT is a conversation library
- Implement the DAG layer speculatively — wait until Adjacency integration
  drives the requirements from real usage
- Rename things without updating the naming history table above
