# Hub — TTT

The `TTT` class is the hub runtime. It is the sole authority for CTO creation,
authoritative Delta merge, and hub-authored event emission.

`TTT` exposes three important public entry points:

- `start_purpose()` — register a Purpose and assign route credentials
- `start_turn()` — create a new canonical CTO from external/bootstrap input
- `take_turn()` — canonical Purpose-to-hub event submission path

## Lifecycles

### `start_turn(...)`

```text
start_turn(...)
    -> validate content profile
    -> apply profile defaults
    -> create CTO
    -> emit cto_created
    -> multicast to registered Purposes
```

take_turn(...)
```text
take_turn(event)
    -> validate Purpose identity and token
    -> validate payload serialization contract
    -> consult event policy
    -> optionally perform built-in hub action
    -> emit resulting hub-authored events if applicable
```


Not every accepted Purpose-authored event must trigger built-in hub action.
TTT is a provenance-first event substrate: all accepted events go through the
hub, while only a subset currently trigger built-in hub behavior such as
Delta merge.

## Reference

::: turnturnturn.hub.TTT
