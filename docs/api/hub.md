# Hub — TTT

The `TTT` class is the hub runtime. It is the sole authority for CTO creation,
Delta merge, and HubEvent emission. All ingress goes through `start_turn()`.

## Lifecycle

```ASCII
start_turn(...)
    └─ validate content profile
    └─ create CTO
    └─ emit cto_created
    └─ multicast to registered Purposes
```

## Reference

::: turnturnturn.hub.TTT
