# Events

TTT has one event substrate with two authorship categories:

- **Hub-authored events** describe facts the hub has made true
- **Purpose-authored events** are submitted to the hub for validation,
  persistence/routing, and optional built-in hub action

All event payloads implement `EventPayloadProtocol` and serialize through
`.as_dict()`.

## Event types

## Hub-authored event types

| Event | Meaning |
| ----- | ------- |
| `cto_created` | A new canonical CTO now exists. |
| `delta_merged` | The hub accepted and merged a Delta into canonical state. |
| `purpose_started` | The hub has registered and started a Purpose. |

## Purpose-authored event types

| Event | Meaning |
| ----- | ------- |
| `delta_proposal` | A Purpose proposes a Delta for authoritative merge. |
| `purpose_completed` | A Purpose reports completion and may trigger built-in hub behavior in future policy. |

## Payload classes

Hub-authored payloads include:

- `CTOCreatedPayload`
- `DeltaMergedPayload`
- `EmptyPayload`

Purpose-authored payloads currently include:

- `DeltaProposalPayload`

## Reference

::: turnturnturn.events.HubEventType

::: turnturnturn.events.PurposeEventType

::: turnturnturn.events.HubEvent

::: turnturnturn.events.DeltaProposalEvent

::: turnturnturn.events.CTOCreatedPayload

::: turnturnturn.events.DeltaMergedPayload

::: turnturnturn.events.DeltaProposalPayload

::: turnturnturn.events.EmptyPayload
