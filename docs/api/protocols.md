# Protocols

TTT uses structural subtyping (Protocols) rather than inheritance. This keeps
the hub decoupled from concrete Purpose implementations.

## Event protocols

TTT also defines structural protocols for event envelopes and payloads:

- `EventPayloadProtocol` — payload objects must implement `.as_dict()`
- `EventProtocol` — minimal event envelope contract
- `PurposeEventProtocol` — event envelope contract for Purpose-authored events,
  including `purpose_id`, `purpose_name`, and `hub_token`

```text
EventProtocol            — minimal event envelope
    └─ PurposeEventProtocol — Purpose-authored event envelope

TurnTakerProtocol        — can receive hub-authored events
    └─ PurposeProtocol   — registered agenda-bearing actor
    
EventPayloadProtocol      — payload serialization contract
```

Implement `PurposeProtocol` for anything you want to register with TTT.
`TurnTakerProtocol` is available if you need a lighter capability role that
participates in the event mesh without being a registered Purpose.

## Reference

::: turnturnturn.protocols.TurnTakerProtocol

::: turnturnturn.protocols.PurposeProtocol

::: turnturnturn.protocols.EventPayloadProtocol

::: turnturnturn.protocols.EventProtocol

::: turnturnturn.protocols.PurposeEventProtocol
