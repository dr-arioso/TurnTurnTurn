# Delta

A `Delta` is a purpose-proposed change submitted to the hub for authoritative
merge. Purposes never mutate CTO state directly — they propose, TTT decides.

Deltas are append-only: TTT does not silently overwrite prior contributions.
The `patch` field is treated as opaque by the hub; its semantics are
owned by the proposing Purpose.

## Reference

::: turnturnturn.delta.Delta
