# Events

TTT has one event substrate with two authorship categories:

- **Hub-authored events** describe facts the hub has made true.
- **Purpose-authored events** are submitted to the hub for validation,
  persistence/routing, optional built-in hub action, and communication
  with other Purposes.

All event payloads implement `EventPayloadProtocol` and serialize through
`.as_dict()`.

## Hub-authored event types

| Event | Meaning |
| ----- | ------- |
| `session_started` | The hub has started a session and recorded persistence provenance. Persistence-only; first event in the log. |
| `purpose_started` | The hub has registered and started a Purpose. |
| `cto_started` | A new canonical CTO now exists. |
| `delta_merged` | The hub accepted and merged a Delta into canonical state. |
| `delta_rejected` | The hub rejected a malformed or invalid Delta proposal and recorded the reason. |
| `session_closing` | The hub has begun orderly shutdown and is signaling Purposes to flush/evacuate. |
| `session_completed` | The session has ended. Persistence-only; final record in the log. |
| `cto_completed` | Reserved terminal CTO lifecycle event for future quiescence/DAG work. |

## Purpose-authored event types

| Event | Meaning |
| ----- | ------- |
| `delta_proposal` | A Purpose proposes a Delta for authoritative merge. |
| `purpose_completed` | A Purpose reports that it has completed its work. |
| `cto_close_request` | A Purpose signals that a CTO is complete from that Purpose's perspective. Currently accepted as a stub for future DAG/quiescence logic. |

## Payload classes

Hub-authored payloads include:

- `CTOStartedPayload`
- `CTOCompletedPayload`
- `DeltaMergedPayload`
- `DeltaRejectedPayload`
- `PurposeStartedPayload`
- `SessionStartedPayload`
- `SessionClosingPayload`
- `SessionCompletedPayload`
- `EmptyPayload`

Purpose-authored payloads include:

- `DeltaProposalPayload`
- `CTOCloseRequestPayload`

## Reference

::: turnturnturn.events.HubEventType

::: turnturnturn.events.PurposeEventType

::: turnturnturn.events.HubEvent

::: turnturnturn.events.DeltaProposalEvent

::: turnturnturn.events.CTOCloseRequestEvent

::: turnturnturn.events.CTOStartedPayload

::: turnturnturn.events.CTOCompletedPayload

::: turnturnturn.events.DeltaMergedPayload

::: turnturnturn.events.DeltaRejectedPayload

::: turnturnturn.events.PurposeStartedPayload

::: turnturnturn.events.SessionStartedPayload

::: turnturnturn.events.SessionClosingPayload

::: turnturnturn.events.SessionCompletedPayload

::: turnturnturn.events.DeltaProposalPayload

::: turnturnturn.events.CTOCloseRequestPayload

::: turnturnturn.events.EmptyPayload