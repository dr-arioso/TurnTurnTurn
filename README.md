# TurnTurnTurn

[![CI](https://github.com/dr-arioso/TurnTurnTurn/actions/workflows/ci.yml/badge.svg)](https://github.com/dr-arioso/TurnTurnTurn/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://www.python.org/downloads/)

---

TTT started as an answer to a surprisingly open question in conversational AI research: **what actually *is* a turn?**

When building research infrastructure for human-AI interaction studies, the honest answer from the field was: an assorted collection of dicts, flat transcript files, and ad-hoc JSON — each project reinventing the same structure with different field names and no provenance story. TTT is the canonical object that was missing: a structured, hub-authoritative unit of conversational or sequential work, with data integrity and replayability built in from the start.

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

```
start_turn(session_id, content_profile, content)
    │
    ▼
  TTT hub
    ├── validate content profile
    ├── create CTO  ──────────────────────────────► cto_created event
    └── dispatch to registered Purposes
              │
              ▼
        Purpose.take_turn(event)
              │
              ▼
           Delta  ────────────────────────────────► delta_merged event
```

TTT does **not** define domain semantics. It provides the structure; you bring the content. The `content_profile` field is the extension point — `"conversation"` is the canonical example, but any profile can be registered with its own required shape.

### Core vocabulary

| Concept | What it is |
|---------|------------|
| **TTT** | The hub runtime. Sole authority for CTO creation, Delta merge, and event emission. |
| **CTO** | Canonical Turn Object. The hub-authoritative work item. Immutable once created. |
| **Purpose** | A registered actor that receives HubEvents and may propose Deltas. |
| **Delta** | A purpose-proposed change. Validated and merged by the hub; never applied directly. |
| **HubEvent** | An authoritative event emitted by the hub on each state transition. The replay substrate. |

---

## Quick start

```python
import asyncio
from uuid import uuid4
from turnturnturn import TTT

async def main():
    ttt = TTT.create()

    turn_id = await ttt.start_turn(
        session_id=uuid4(),
        content_profile="conversation",
        content={"speaker": "user", "text": "hello"},
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

TTT is in active architectural development. The core object model and hub semantics are stable; the DAG eligibility layer and persistence are in progress. Names and APIs may still shift before v1.0.

See [`docs/ttt_architecture_v0_15.md`](docs/ttt_architecture_v0_15.md) for the current design.

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
