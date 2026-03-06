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
        content={"speaker_id": "usr_a3f9", "text": "hello"},
    )
    print(f"Created turn: {turn_id}")

asyncio.run(main())
```

## Core concepts

| Concept | Description |
|---------|-------------|
| **TTT** | The hub runtime. Authoritative for CTO creation, Delta merge, and event emission. |
| **CTO** | Canonical Turn Object. The hub-authoritative work item. |
| **Purpose** | A registered agenda-bearing actor that receives HubEvents and may emit Deltas. |
| **Delta** | A purpose-proposed change, merged authoritatively by TTT. |
| **HubEvent** | An authoritative event emitted by TTT. The primary provenance surface. |

## Status

This project is in active architectural development. Names, APIs, and module
layout are still being refined. See the [Architecture](ttt_architecture_v0_16.md)
doc for current design direction.
