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
from turnturnturn import TTT, BasePurpose
from turnturnturn.events import HubEvent

class EchoPurpose(BasePurpose):
    name = "echo"

    def __init__(self):
        super().__init__()
        self.id = uuid4()

    async def _handle_event(self, event: HubEvent) -> None:
        print(f"Received: {event.event_type.value}")

async def main():
    ttt = TTT.start()

    purpose = EchoPurpose()
    await ttt.start_purpose(purpose)

    turn_id = await ttt.start_turn(
        session_id=uuid4(),
        content_profile="conversation",
        content={"speaker": {"id": "usr_a3f9"}, "text": "hello"},
    )
    print(f"Created turn: {turn_id}")

asyncio.run(main())
```

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

## Status

This project is in active architectural development. The core object model,
hub semantics, profile system, and Purpose dispatch are stable. The DAG
eligibility layer and persistence are not yet implemented.

See the [Architecture](ttt_architecture_v0_19.md) doc for current design direction.
