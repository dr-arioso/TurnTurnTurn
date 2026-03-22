# Hub — TTT

The `TTT` class is the hub runtime. It is the sole authority for CTO creation,
authoritative Delta merge, and hub-authored event emission.

`TTT` exposes the following public entry points:

- `TTT.start(persistence_purpose, *, strict_profiles=False)` — start the hub
  with a required persistence backend
- `TTT.register_event_type(event_type, *, multicast=True)` — register a custom
  dotted-namespace event type with the pluggable relay
- `start_purpose()` — register a Purpose and assign route credentials
- `start_turn()` — create a new canonical CTO from authenticated bootstrap input
- `take_turn()` — canonical Purpose-to-hub event submission path
- `close()` — initiate orderly session shutdown

## Lifecycles

### `TTT.start(...)`

```text
TTT.start(persistence_purpose, ...)
    -> validate persistence backend contract
    -> load built-in profiles
    -> assign persistence credentials
    -> write session_started directly to persistence
```

`session_started` is persistence-only. It is written before any domain Purpose
registration or dispatch and is the first record in the event log.


**`start_purpose(...)`**
```text
start_purpose(...)
    -> assign hub-issued credentials
    -> register Purpose
    -> emit purpose_started
    -> multicast to registered Purposes
```

**`start_turn(...)`**
```text
start_turn(...)
    -> authenticate submitter via hub_token
    -> validate content profile
    -> apply profile defaults
    -> create CTO
    -> emit cto_started
    -> multicast to registered Purposes
```
**`take_turn(...)`**
```text
take_turn(event)
    -> validate Purpose identity and token
    -> validate payload serialization contract
    -> consult event policy
    -> optionally perform built-in hub action
    -> emit resulting hub-authored events if applicable
```
Not every accepted Purpose-authored event is **hub-advisory**; that is, not all Purpose-authored events must trigger built-in hub action.
TTT is a provenance-first event substrate: all accepted events go through the
hub, while only a subset currently trigger built-in hub behavior such as
Delta merge.

**`TTT.register_event_type(event_type, *, multicast=True)`**

Class-level registration of a custom event type string into the module-level
`_CUSTOM_EVENT_POLICY` dict. Enables domain packages to define their own event
namespaces without modifying `HubEventType`.

```text
register_event_type(event_type, multicast=True)
    -> validate dotted-namespace format (e.g. "adjacency.stimulus")
    -> guard against conflicting re-registration
    -> write event_type → multicast into _CUSTOM_EVENT_POLICY
```

Constraints on `event_type`:
- Must be non-empty
- Alphanumeric after stripping `.` and `_` — no special characters
- Cannot start or end with `.`
- Re-registration with the same `multicast` value is a no-op; re-registration
  with a different `multicast` value raises `ValueError`

`take_turn()` consults `_CUSTOM_EVENT_POLICY` after exhausting the native
`PurposeEventType` enum. If the event type is found, `_relay_custom_event()`
wraps the payload as a `HubEvent` with `event_type: str` and multicasts it
to all registered Purposes.

Call `register_event_type()` once per process before the first `Session.start()`.
Re-registration with the same arguments is safe.

**`close(...)`**
```text
close(reason=...)
    -> emit session_closing to all registered Purposes
    -> (v0) do not wait for quiescence yet
    -> emit session_completed to persistence only
```
`session_completed` is persistence-only and is the final record in the log.

Reference

::: turnturnturn.hub.TTT