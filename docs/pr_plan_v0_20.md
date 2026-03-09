# TTT v0.20 — Archivist, Event Taxonomy, and Coverage

**Branch:** `feature/archivist-and-event-taxonomy`

## What this PR does

Closes three open items from the v0.19 review:

1. Completes and rationalises the event taxonomy — renames, additions,
   and a two-phase session shutdown model.
2. Delivers Archivist: a real durable `PersistencePurpose` subclass with
   pluggable internal backends, replacing the dead `historian.py` seam.
3. Fills the coverage gaps identified in the v0.19 review.

---

## Settled design decisions

### Event taxonomy

| Event | Type | Delivered to | Trigger |
|---|---|---|---|
| `SESSION_STARTED` | hub | persistence only | first `start_purpose()` |
| `SESSION_CLOSING` | hub | all Purposes | `ttt.close()` / quiescence (future) |
| `SESSION_COMPLETED` | hub | persistence only | after domain Purposes clear |
| `CTO_STARTED` | hub | all | `start_turn()` |
| `CTO_COMPLETED` | hub | all | quiescence / `CTOCloseRequest` (stub) |
| `DELTA_MERGED` | hub | all | successful merge |
| `DELTA_REJECTED` | hub | all | malformed proposal |
| `PURPOSE_STARTED` | hub | all | `start_purpose()` |
| `PURPOSE_COMPLETED` | Purpose → hub | hub | Purpose signals done |
| `DELTA_PROPOSAL` | Purpose → hub | hub | Purpose proposes change |
| `CTOCloseRequest` | Purpose → hub | hub | originator signals satisfaction (stub) |

`CTO_CREATED` is retired; `CTO_STARTED` is its replacement throughout.

### Session shutdown (two-phase)

`SESSION_CLOSING` is broadcast to all Purposes. Domain Purposes use it
as their evacuation signal — flush state, submit final Deltas, send
`PURPOSE_COMPLETED`. The hub waits for quiescence or a timeout (DAG
concern, future). After domain Purposes have cleared, `SESSION_COMPLETED`
is delivered to persistence Purpose(s) only. It is the final record.

`ttt.close(reason=...)` is the explicit trigger. Quiescence-triggered
closing is deferred to the DAG layer.

`SESSION_STARTED` and `SESSION_COMPLETED` are both persistence-only
events — outside the normal `_multicast()` path. `SESSION_STARTED` is
written before the first domain Purpose is registered; `SESSION_COMPLETED`
is written after the last one disconnects.

`SessionCompletedPayload` carries `is_last_out: bool = True`.

### Archivist internal backend protocol

Archivist is a `PersistencePurpose` subclass. From the hub's perspective
it is an opaque durable Purpose. Internally it routes events to pluggable
backends.

Each backend satisfies a single-method protocol:

```python
class ArchivistBackendProtocol(Protocol):
    async def accept(self, event: HubEvent) -> None: ...
```

Both stream backends (JSONL, one record per event) and document backends
(accumulated per session, finalised on `SESSION_COMPLETED`) implement the
same method. Document backends accumulate internally and flush on
`SESSION_COMPLETED`.

Backend configuration at construction time includes: event type filter,
content profile filter, output path, and serialization shape. Different
`content_profile` values produce different output files. Real-time backend
tuning via specially-constructed events is noted as a future capability
(out of scope for v0).

`write_event()` is retired as a public contract. Archivist implements
`_handle_event()` directly and fans out to its configured backends.
`InMemoryPersistencePurpose` retains `write_event()` as its internal
implementation — it is the canonical test/dev backend and failover
double.

### `DeltaProposalPayload` relocation

Currently in `purpose_events.py` by historical accident. Moves to
`hub_events.py` alongside the other payload classes. The import path
through `events/__init__.py` is preserved so no consuming code breaks.

### `.as_dict()` idempotency

`EventPayloadProtocol.as_dict()` is documented as a pure function — same
output every call, no side effects. Enforced by tests (calling `as_dict()`
twice and asserting identical output) rather than the type system.

---

## Commits

### Commit 1 — Rename and extend the event taxonomy

**Files changed:**

- `src/turnturnturn/events/hub_events.py`
  - Rename `CTO_CREATED` → `CTO_STARTED` in `HubEventType`
  - Add `CTO_COMPLETED`, `DELTA_REJECTED`, `SESSION_STARTED`,
    `SESSION_CLOSING`, `SESSION_COMPLETED` to `HubEventType`
  - Move `DeltaProposalPayload` here from `purpose_events.py`
  - Add payload classes:
    - `CTOStartedPayload` — wraps `CTOIndex` dict; replaces
      `CTOCreatedPayload`
    - `CTOCompletedPayload` — carries full CTO dict (self-contained;
      Archivist needs no librarian reference)
    - `DeltaRejectedPayload` — rejected delta dict + `reason: str`
    - `SessionStartedPayload` — hub_id, ttt_version, persister_name,
      persister_id, persister_is_durable, strict_profiles
    - `SessionClosingPayload` — `reason: str`, `timeout_ms: int | None`
    - `SessionCompletedPayload` — `is_last_out: bool = True`

- `src/turnturnturn/events/purpose_events.py`
  - Remove `DeltaProposalPayload` (moved to hub_events.py)
  - Add `CTOCloseRequest` to `PurposeEventType`
  - Add `CTOCloseRequestEvent` and `CTOCloseRequestPayload` (turn_id only)

- `src/turnturnturn/events/__init__.py`
  - Update all exports; add `DeltaProposalPayload` re-export from new
    location; add all new payload and event classes; retire
    `CTOCreatedPayload` export (keep as deprecated alias for one version)

- `src/turnturnturn/__init__.py`
  - Mirror export changes

**No hub behaviour changes in this commit.** `hub.py` still references
`CTO_CREATED` internally — that moves in Commit 2. This commit is
taxonomy only, so the diff is reviewable in isolation.

**Tests:** none added here — existing tests will break on the rename and
are fixed in Commit 2.

---

### Commit 2 — Update hub to use new event types; add `ttt.close()`

**Files changed:**

- `src/turnturnturn/hub.py`
  - Replace all `HubEventType.CTO_CREATED` with `HubEventType.CTO_STARTED`
  - Replace all `CTOCreatedPayload` with `CTOStartedPayload`
  - `start_purpose()`: emit `SESSION_STARTED` (persistence-only) when the
    first Purpose registered is a `CTOPersistencePurposeProtocol`; emit
    `PURPOSE_STARTED` to all via `_multicast()` for subsequent registrations
  - `_merge_delta()`: emit `DELTA_REJECTED` (with reason string) instead of
    raising bare `ValueError` / `KeyError` — exceptions still raised after
    emission so callers are not silently swallowed
  - Register `CTOCloseRequest` in `_EVENT_POLICY` as `handler=None` (no-op
    stub; DAG layer will implement)
  - Add `async def close(self, *, reason: str = "normal") -> None`:
    1. Emit `SESSION_CLOSING` via `_multicast()` to all Purposes
    2. Await quiescence (v0: immediate; no timeout logic yet)
    3. Emit `SESSION_COMPLETED` (persistence-only) to registered
       persistence Purpose(s)
  - `_multicast()`: add `persistence_only: bool = False` parameter;
    when True, deliver only to persistence Purposes

- `src/turnturnturn/errors.py`
  - No changes — `DELTA_REJECTED` is an event, not an exception; the
    existing `ValueError`/`KeyError` raises are preserved

**Tests updated:**

- All existing tests that reference `CTO_CREATED` or `CTOCreatedPayload`
  updated to `CTO_STARTED` / `CTOStartedPayload`
- All `hub` fixture calls verified against new `start_purpose()` emission
  behaviour (PURPOSE_STARTED now emitted — event-type filtering in tests
  already handles this from v0.19)

**New tests:**

- `test_close_emits_session_closing_to_all_purposes`
- `test_close_emits_session_completed_to_persistence_only`
- `test_close_session_completed_payload_is_last_out`
- `test_merge_delta_unknown_turn_id_emits_delta_rejected`
- `test_merge_delta_non_list_patch_emits_delta_rejected`
- `test_start_purpose_first_emits_session_started_to_persistence`
- `test_start_purpose_session_started_not_broadcast_to_domain_purposes`

---

### Commit 3 — Delete `historian.py`; add `ArchivistBackendProtocol`

**Files changed:**

- `src/turnturnturn/historian.py` — **deleted**
- `src/turnturnturn/archivist.py` — new file containing:
  - `ArchivistBackendProtocol` — single-method `async def accept(self, event: HubEvent) -> None`
  - `ArchivistBackendConfig` — dataclass: `event_types: set[HubEventType] | None` (None = all), `content_profile: str | None` (None = all), plus backend-specific fields in subclasses
  - No concrete backends yet — those are Commits 4 and 5
  - No `Archivist` class yet — that is Commit 6

- `src/turnturnturn/__init__.py`
  - Remove `InMemoryHistorian`, `JsonlHistorian` exports
  - Add `ArchivistBackendProtocol`

**Why split from Commit 4?** The protocol definition is the stable
contract. Concrete backends depend on it. Keeping the protocol in its
own commit makes the dependency direction clear in the history.

---

### Commit 4 — `JsonlArchivistBackend` (stream shape)

**Files changed:**

- `src/turnturnturn/archivist.py` — add `JsonlArchivistBackend`:
  - Satisfies `ArchivistBackendProtocol`
  - Constructor: `path: Path`, inherits `ArchivistBackendConfig` filters
  - `accept()`: serialises the event via `_event_serialization.hub_event_record()`,
    appends one JSON line to `path`; creates parent directories if absent
  - `is_durable: bool = True`
  - Append is synchronous (blocking file I/O in async context is acceptable
    for v0; noted as a future `asyncio` improvement)
  - No deduplication — `JsonlArchivistBackend` appends unconditionally;
    idempotency is `InMemoryPersistencePurpose`'s responsibility as failover
    double

**Tests — `test_jsonl_archivist_backend.py`:**

- `test_jsonl_backend_writes_event_record`
- `test_jsonl_backend_appends_across_multiple_events`
- `test_jsonl_backend_creates_parent_dirs`
- `test_jsonl_backend_restart_appends_to_existing_file`
- `test_jsonl_backend_respects_event_type_filter`
- `test_jsonl_backend_respects_content_profile_filter`
- `test_jsonl_backend_event_record_keys` — assert exact key set
- `test_jsonl_backend_sort_keys_stable` — `sort_keys=True` on all writes

---

### Commit 5 — `SessionDocumentArchivistBackend` (document shape, stub)

**Files changed:**

- `src/turnturnturn/archivist.py` — add `SessionDocumentArchivistBackend`:
  - Satisfies `ArchivistBackendProtocol`
  - Constructor: `path: Path`
  - Accumulates events in memory as `accept()` is called
  - On `SESSION_COMPLETED`: writes a single JSON document to `path`
    containing metadata header + ordered events array
  - Document shape mirrors the TraceProbe format: top-level keys are
    `id`, `metadata`, `events`
  - Marked as a stub — the metadata header and full TraceProbe-compatible
    shape are future work; the accumulate-and-flush pattern is what this
    commit establishes

**Tests — `test_session_document_backend.py`:**

- `test_session_document_backend_writes_on_session_completed`
- `test_session_document_backend_accumulates_events_in_order`
- `test_session_document_backend_does_not_write_before_session_completed`
- `test_session_document_backend_output_is_valid_json`

---

### Commit 6 — `Archivist` class

**Files changed:**

- `src/turnturnturn/archivist.py` — add `Archivist(PersistencePurpose)`:
  - Constructor: `backends: list[tuple[ArchivistBackendConfig, ArchivistBackendProtocol]]`
  - `is_durable: bool` — True if at least one configured backend is durable
  - `_handle_event()`: iterates backends; for each, checks event type and
    content profile filters from config; calls `await backend.accept(event)`
    for matching backends
  - `name = "archivist"`
  - `id = uuid4()` set at construction

- `src/turnturnturn/__init__.py` — add `Archivist`, `JsonlArchivistBackend`,
  `SessionDocumentArchivistBackend`, `ArchivistBackendProtocol` to exports

**Tests — `test_archivist.py`:**

- `test_archivist_is_durable_true_when_any_backend_is_durable`
- `test_archivist_is_durable_false_when_no_durable_backend`
- `test_archivist_routes_event_to_matching_backends`
- `test_archivist_does_not_route_to_filtered_out_backends`
- `test_archivist_multiple_backends_all_receive_matching_event`
- `test_archivist_different_profiles_route_to_different_backends`
- `test_archivist_end_to_end_via_hub` — full hub integration: register
  Archivist with a `JsonlArchivistBackend`, run a turn, assert JSONL file
  contains expected records

---

### Commit 7 — Fix truncated test; add missing hub coverage

**Files changed:**

- `tests/test_hub_take_turn.py`
  - Fix `test_take_turn_unknown_event_type_raises` — give it a real
    assertion body
  - Add `test_take_turn_purpose_completed_is_noop` — `PURPOSE_COMPLETED`
    accepted, returns `None`
  - Add `test_take_turn_rejects_mismatched_purpose_id`
  - Add `test_take_turn_rejects_payload_as_dict_non_dict`

- `tests/test_hub.py`
  - Add `test_start_turn_persistence_token_rejected` — persistence
    Purpose's token must not be accepted as a `start_turn()` submitter
  - Add `test_bootstrap_persister_uses_unknown_version_when_package_metadata_missing`

---

### Commit 8 — `_event_serialization` coverage; `.as_dict()` idempotency

**Files changed:**

- `tests/test_serialization.py` — new file:
  - `test_hub_event_record_shape` — exact key set
  - `test_purpose_event_record_shape` — exact key set
  - `test_cto_snapshot_record_shape` — exact key set
  - `test_event_type_value_with_enum`
  - `test_event_type_value_with_plain_string`
  - `test_uuid_str_with_uuid`
  - `test_uuid_str_with_none`
  - `test_cto_created_payload_as_dict_is_idempotent`
  - `test_delta_merged_payload_as_dict_is_idempotent`
  - `test_delta_proposal_payload_as_dict_is_idempotent`
  - `test_session_started_payload_as_dict_is_idempotent`

---

### Commit 9 — Update arch doc and AGENTS.md to v0.20

**Files changed:**

- `docs/ttt_architecture_v0_19.md` → `docs/ttt_architecture_v0_20.md`
  - §0.1 Invariants: add session shutdown invariants
  - §1 Core nouns: add Archivist, ArchivistBackendProtocol, SESSION_CLOSING,
    SESSION_COMPLETED; update start_turn noun to reference CTO_STARTED
  - §3 Public API: add `ttt.close()`
  - §4 Lifecycle: add session closing phase (4.9, 4.10)
  - §7 Event taxonomy: full updated table
  - §9 Module map: add `archivist.py`; remove `historian.py`
  - §10 Non-goals: remove Archivist (landed); add document shape
    completion, async file I/O, quiescence-triggered SESSION_CLOSING
  - §11 Open questions: add backend real-time tuning via events (deferred)
  - §12 Migration notes: v0.20 section

- `AGENTS.md`
  - Current status: Archivist landed; historian.py deleted
  - Naming history: `CTO_CREATED` → `CTO_STARTED`;
    `CTOCreatedPayload` → `CTOStartedPayload`;
    `historian.py` / `InMemoryHistorian` / `JsonlHistorian` → retired
  - Do not: add entry for `write_event()` as public contract (retired)

---

## Working pattern

Same as v0.19: new files provided in full, edits to existing files as
str_replace targets. Human runs pytest after each commit, pastes failures
only if any. Code-as-docs-as code. Docstrings and comments form our API documentation. Appropriate unit tests with each commit.

## Open questions going into implementation

None blocking. The following are noted for the DAG layer:

- Quiescence-triggered `SESSION_CLOSING` (what counts as quiescent?)
- `CTOCloseRequest` honoured by the hub (what does the DAG check?)
- Async file I/O for `JsonlArchivistBackend` (acceptable as sync for v0)
- Document shape completion for `SessionDocumentArchivistBackend`
  (TraceProbe-compatible metadata header is future work)
- Real-time backend tuning via specially-constructed events (out of scope
  for v0, noted in arch doc)
