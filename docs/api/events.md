# Events

TTT has one event substrate with two authorship categories:

- **Hub-authored events** describe facts the hub has made true.
- **Purpose-authored events** are submitted to the hub for validation,
  persistence/routing, optional built-in hub action, and communication
  with other Purposes.

All event payloads implement `EventPayloadProtocol` and serialize through
`.as_dict()`.

This page mixes current implementation details with the public event surface.
For the intended authorship split for bootstrap and shutdown lifecycle events,
see [Bootstrap and Lifecycle](../architecture/bootstrap_lifecycle.md).
For the broader substrate model, see [Core Architecture](../architecture/core_architecture.md).

## Hub-authored event types

| Event | Meaning |
| ----- | ------- |
| `session_started` | Session bootstrap provenance. In the current implementation this is persisted through the hub bootstrap path; the intended direction is Persist-authored lifecycle provenance. |
| `purpose_started` | Purpose startup provenance. In the current implementation this is hub-emitted during registration; the intended direction treats it as lifecycle/provenance information rather than a registration handshake. |
| `cto_started` | A new canonical CTO now exists. |
| `delta_merged` | The hub accepted and merged a Delta into canonical state. |
| `delta_rejected` | The hub rejected a malformed or invalid Delta proposal and recorded the reason. |
| `session_closing` | The hub has begun orderly shutdown and is signaling Purposes to flush/evacuate. |
| `session_close_pending` | Domain Purposes are clear and only persistence remains active. Persistence-only. |
| `session_completed` | The session has ended. Persistence-only; final record in the log. |
| `cto_completed` | Reserved terminal CTO lifecycle event for future quiescence/DAG work. |

## Purpose-authored event types

| Event | Meaning |
| ----- | ------- |
| `propose_delta` | A Purpose proposes a Delta for authoritative merge. |
| `request_cto` | A Purpose asks persistence to import a canonical `cto_json` document into the mesh. |
| `cto_imported` | The persistence Purpose reports a normalized imported CTO document for hub adoption. |
| `request_session_end` | A Purpose requests orderly session shutdown. |
| `purpose_completed` | A Purpose reports that it has completed its work. |
| `request_cto_close` | A Purpose signals that a CTO is complete from that Purpose's perspective. Currently accepted as a stub for future DAG/quiescence logic. |

## Custom event types

Domain packages can define their own event namespaces without modifying
`HubEventType` or `PurposeEventType`. Register a dotted-namespace string with
`TTT.register_event_type()` before the first `session.start()`:

```python
from turnturnturn.hub import TTT

TTT.register_event_type("adjacency.prompt_subject", multicast=True)
TTT.register_event_type("adjacency.subject_response", multicast=True)
```

Custom events submitted via `take_turn()` are:

- Validated against the registered policy.
- Wrapped as a `HubEvent` with `event_type: str` and multicast to all
  registered Purposes (when `multicast=True`).
- Persisted alongside built-in hub events.

`HubEvent.event_type` is typed `HubEventType | str` to accommodate both
built-in and custom events. Purposes handling custom events should compare
against the string constant directly:

```python
from adjacency.events import PROMPT_SUBJECT  # "adjacency.prompt_subject"

async def _handle_event(self, event: HubEvent) -> None:
    if event.event_type == PROMPT_SUBJECT:
        ...
```

See `TTT.register_event_type()` for format constraints and re-registration
semantics.

## Payload classes

Hub-authored payloads include:

- `CTOStartedPayload`
- `CTOCompletedPayload`
- `DeltaMergedPayload`
- `DeltaRejectedPayload`
- `PurposeStartedPayload`
- `SessionStartedPayload`
- `SessionClosingPayload`
- `SessionClosePendingPayload`
- `SessionCompletedPayload`
- `EmptyPayload`

Purpose-authored payloads include:

- `ProposeDeltaPayload`
- `RequestCTOPayload`
- `CTOImportedPayload`
- `RequestSessionEndPayload`
- `PurposeCompletedPayload`
- `RequestCTOClosePayload`

## Reference

::: turnturnturn.events.HubEventType

::: turnturnturn.events.PurposeEventType

::: turnturnturn.events.HubEvent

::: turnturnturn.events.ProposeDelta

::: turnturnturn.events.RequestCTOClose

::: turnturnturn.events.CTOStartedPayload

::: turnturnturn.events.CTOCompletedPayload

::: turnturnturn.events.DeltaMergedPayload

::: turnturnturn.events.DeltaRejectedPayload

::: turnturnturn.events.PurposeStartedPayload

::: turnturnturn.events.SessionStartedPayload

::: turnturnturn.events.SessionClosingPayload

::: turnturnturn.events.SessionClosePendingPayload

::: turnturnturn.events.SessionCompletedPayload

::: turnturnturn.events.ProposeDeltaPayload

::: turnturnturn.events.RequestCTOPayload

::: turnturnturn.events.CTOImportedPayload

::: turnturnturn.events.RequestSessionEndPayload

::: turnturnturn.events.PurposeCompletedPayload

::: turnturnturn.events.RequestCTOClosePayload

::: turnturnturn.events.EmptyPayload
