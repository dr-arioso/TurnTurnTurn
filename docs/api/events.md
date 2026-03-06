# Events

HubEvents are the authoritative record of what TTT has made true. The event
stream is the primary provenance surface — the canonical answer to "who
contributed what, when" comes from replaying events, not from in-memory state.

## Event types

| Event | When emitted |
| ----- | ------------ |
| `cto_created` | A new CTO now exists and is canonical. |
| `delta_merged` | TTT has accepted and merged a Delta. |
| `purpose_registered` | TTT has accepted a Purpose registration. |
| `purpose_completed` | A Purpose has completed a unit of work for a CTO. |

## Reference

::: turnturnturn.events.HubEventType

::: turnturnturn.events.HubEvent

::: turnturnturn.events.payload_cto_created
