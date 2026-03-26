# TurnTurnTurn

[![CI](https://github.com/dr-arioso/TurnTurnTurn/actions/workflows/ci.yml/badge.svg)](https://github.com/dr-arioso/TurnTurnTurn/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://www.python.org/downloads/)

---

TTT started as an answer to a surprisingly open question in conversational AI research: **what actually *is* a turn?**

When building research infrastructure for human-AI interaction studies, the honest answer from the field was: an assorted collection of dicts, flat transcript files, and ad-hoc JSON — each project reinventing the same structure with different field names and no provenance story. CTO is the canonical object that was missing: a structured, authoritative unit of conversational or sequential work, with data integrity and replayability built in from the start.

From there, the applications broadened. TTT is useful anywhere a single input needs to move through multiple processors — human-AI interaction pipelines, multi-LLM coordination, AI observability, annotation workflows, content enrichment. The abstraction generalizes cleanly because the core problem is always the same: **something arrives, multiple things need to happen to it, and you need to know exactly what happened and in what order.**

TTT is built for anyone who needs:

- **Incremental enrichment** — multiple processors each contribute to a shared work item without overwriting each other
- **Dependency ordering** — this has to happen before that, enforced by the hub
- **Async safety** — concurrent processors without race conditions on canonical state
- **Data integrity** — nothing writes to canonical state directly; every change is *proposed* and validated at merge time
- **Full replayability** — the event stream is the ground truth; replay any session against a new processor version to verify behavior before shipping

That last point is the one that tends to land hardest. Most pipelines have no good answer to "how do we test the new version of our annotator against real historical data?" TTT's answer is: rerun the event stream. The worst a buggy processor can do is have its Delta rejected. The audit trail survives regardless.

---

## How it works

TTT is built around a single canonical object:

**CTO** — Canonical Turn Object. Created by the hub, never mutated directly. Processors read CTOs and propose changes via **Deltas**; the hub validates and merges them. Every transition emits a **HubEvent**. The event stream is the authoritative record.

```text
start_turn(content_profile, content, hub_token, *, session_id=...)
    │
    ▼
  TTT hub
    ├── authenticate submitter
    ├── validate content profile
    ├── create CTO  ──────────────────────────────► cto_started event  { cto_index }
    └── dispatch to registered Purposes (per-recipient, hub_token stamped)
              │
              ▼
        Purpose._handle_event(event)
              │
              ▼
        hub.take_turn(delta_proposal)  ─────────► delta_merged event  { delta, cto_index }
```

HubEvent payloads carry a **`CTOIndex`** — a lightweight routing reference, not a full CTO snapshot. Purposes that need full content or observations call `ttt.librarian.get_cto(turn_id)`. This keeps the event bus lean regardless of how much observation state accumulates.

TTT does **not** define domain semantics. It provides the structure; you bring the content. The `content_profile` field is the extension point — `"conversation"` is the canonical example, but any profile can be registered with its own required shape.

## Quick start

This example shows the current minimal runtime flow. For the intended
Persist-first bootstrap and explicit session-owner lifecycle model, see
[`docs/architecture/bootstrap_lifecycle.md`](docs/architecture/bootstrap_lifecycle.md).

```python
import asyncio
from uuid import uuid4
from turnturnturn import TTT, BasePurpose, InMemoryPersistencePurpose
from turnturnturn.events import HubEvent

class EchoPurpose(BasePurpose):
    name = "echo"

    def __init__(self):
        super().__init__()
        self.id = uuid4()

    async def _handle_event(self, event: HubEvent) -> None:
        print(f"Received: {event.event_type.value}")

async def main():
    ttt = TTT.start(InMemoryPersistencePurpose())

    purpose = EchoPurpose()
    await ttt.start_purpose(purpose)

    turn_id = await ttt.start_turn(
        content_profile="conversation",
        content={"speaker": {"id": "usr_a3f9"}, "text": "hello"},
        hub_token=purpose.token,
        session_id=uuid4(),
    )
    print(f"Created turn: {turn_id}")

asyncio.run(main())
```

---

## Requirements

Python 3.12+

## Installation

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

---

## Status

TTT is in active architectural development. The core object model, hub semantics,
profile system, Purpose dispatch, and persistence substrate are now implemented.
The DAG eligibility/quiescence layer and parts of the bootstrap/lifecycle model
are still evolving.

For docs, start here:

- [`docs/index.md`](docs/index.md) — docs entry point
- [`docs/architecture/bootstrap_lifecycle.md`](docs/architecture/bootstrap_lifecycle.md) — authoritative lifecycle architecture
- [`docs/architecture/core_architecture.md`](docs/architecture/core_architecture.md) — substrate architecture overview
- [`docs/api/hub.md`](docs/api/hub.md) — current hub API surface

The README is intentionally brief. Lifecycle architecture should live in the
docs, not be duplicated here.

---

## Developer workflow

```bash
# Tests
pytest --cov=turnturnturn
coverage html

# Lint / format / type check / docstring coverage
pre-commit install
pre-commit run --all-files

# Dependency audit
safety check
pip-audit
```

See the [Developer Guide](docs/dev-guide.md) for the full docs workflow including `mkdocs serve`.

---

## License

MIT

