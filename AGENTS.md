# TurnTurnTurn — Agent Orientation

## What this is

TTT is a hub runtime built around the Canonical Turn Object (CTO). The hub is
the sole authority for CTO creation and canonical state. Processors (Purposes)
propose changes via Deltas; the hub validates and merges them. Nothing writes
to canonical state directly.

## Current status

- Core object model and hub semantics: stable
- Profile system (Profile, ProfileRegistry, FieldSpec): stable
- BasePurpose (hub token validation, `_handle_event` dispatch): stable
- Error hierarchy (TTTError, UnauthorizedDispatchError, UnboundPurposeError): stable
- CTOIndex and hub CTO store (`_ctos`, `get_cto()`): stable
- Delta merge (`merge_delta()`): stable
- DAG eligibility layer: not yet implemented (`dag.py` is a stub)
- Persistence: not yet implemented
- `ids.py`: empty stub, not yet implemented
- Delta versioning (`last_event_id` / `based_on_event_id`): TODOs placed in code, not yet implemented

## Key naming history

The following names are retired. If you see them anywhere in the codebase
they are stragglers and should be updated:

| Retired | Replacement |
|---------|-------------|
| `TurnSnargle` | — (concept removed; use `start_turn()` directly) |
| `submit_snargle()` | `ttt.start_turn()` |
| `turn_received` | `cto_created` |
| `content["speaker_id"]` (flat) | `content["speaker"]["id"]` (nested) |
| `CTO.speaker` | `CTO.speaker_id`, `CTO.speaker_role`, `CTO.speaker_label` |
| `validate_content_profile()` | `Profile.validate()` via `ProfileRegistry` |
| `apply_conversation_defaults()` | `Profile.apply_defaults()` via `ProfileRegistry` |
| `_speaker_registry` on hub | `_session_contexts` (opaque; profile-owned contents) |
| full CTO in event payload (`cto_dict`) | `CTOIndex` in event payload (`cto_index_dict`) |

## The invariants that matter most

**No profile-specific code in core modules.** `cto.py` and `hub.py` must
remain profile-agnostic. If you find yourself adding a branch, import, or
field that refers to "conversation", "speaker", or any other profile concept
in either of those files, stop. The profile system exists to prevent exactly
that. Add a `Profile` subclass or extend `FieldSpec` instead.

**Purposes must not call `take_turn()` on each other.** The only valid
source of a HubEvent is the hub. `BasePurpose.take_turn()` enforces this —
it validates `hub_token` on every call and raises `UnauthorizedDispatchError`
on mismatch. If you find yourself calling `some_purpose.take_turn(event)`
from outside the hub, stop. Propose a Delta instead; the hub decides what
happens next.

**Subclass `BasePurpose`, not `PurposeProtocol` directly.** Raw
`PurposeProtocol` implementors bypass token validation and are for test
doubles only. Production Purposes subclass `BasePurpose` and implement
`_handle_event()`. Never override `take_turn()`.

## How profiles work

Profiles are registered with `ProfileRegistry` (process-scoped class-level
registry). The hub looks up profiles at `start_turn()` time by string id.
The CTO carries only `{"id": ..., "version": ...}` — no object references.
`CTO.__getattr__` dispatches to `ProfileRegistry.resolve()` for attribute
access. Resolution walks `FieldSpec.path` into the nested content dict —
the flat accessor name (e.g. `speaker_id`) is a CTO handle only, not a
content key. The hub passes an opaque mutable `session_context` dict to
`Profile.apply_defaults()` — profiles own its contents entirely.

To add a new profile: construct a `Profile` with `FieldSpec` declarations,
call `TTT.register_profile()`. No core changes required. See CONTRIBUTING.md.

## How event payloads work

HubEvent payloads carry a `CTOIndex` — not a full CTO snapshot. This keeps
the event bus lean. Purposes that need full CTO state call
`TTT.get_cto(turn_id)`. The `ctoPersistP` pattern: receive `CTOIndex` in
event, call `get_cto()`, persist full canonical state.

Each HubEvent envelope is **per-recipient** — `_multicast()` constructs a
fresh envelope per Purpose stamped with that Purpose's `hub_token`. Tokens
are never visible across Purpose boundaries.

## Before you commit

```bash
pytest --cov=turnturnturn
pre-commit run --all-files   # ruff, black, isort, mypy --strict, interrogate
```

## Before you change a public interface

Read `docs/ttt_architecture_v0_17.md`. The principles in §2 are load-bearing.
Changes that would require a Purpose to write canonical state directly, or that
add domain semantics to the hub or CTO, are wrong by design, not by accident.

## Do not

- Add any profile-specific code to `cto.py` or `hub.py`
- Add domain semantics to the hub or CTO — `conversation` is an example profile,
  not evidence that TTT is a conversation library
- Call `take_turn()` on a Purpose from outside the hub
- Override `take_turn()` in a `BasePurpose` subclass — implement `_handle_event()` instead
- Implement the DAG layer speculatively — wait until Adjacency integration
  drives the requirements from real usage
- Rename things without updating the naming history table above
