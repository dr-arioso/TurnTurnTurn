# Delta

A `Delta` is a Purpose-proposed change submitted to the hub for authoritative
merge. Purposes never mutate CTO state directly — they submit
`DeltaProposalEvent`s through `hub.take_turn(...)`, and TTT decides whether and
how the proposal becomes canonical state.

Deltas are append-only. The hub enforces that every `patch` value is a list and
extends the proposing Purpose’s observation namespace with those values. TTT
does not silently overwrite or delete prior observations.

The `Delta` itself is the payload-level proposal object. The hub-facing event
envelope is `DeltaProposalEvent`.

## Provenance

`based_on_event_id` records which canonical CTO version the proposing Purpose
was reasoning from when it constructed the Delta. This is provenance metadata,
not an optimistic-locking or conflict-rejection mechanism.

## Reference

::: turnturnturn.delta.Delta
