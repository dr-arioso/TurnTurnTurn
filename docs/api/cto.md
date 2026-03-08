# CTO — Canonical Turn Object

A `CTO` is the hub-authoritative work item created by `TTT.start_turn()`. It is
immutable once created. Purposes read CTOs and propose changes via
[Deltas](delta.md) rather than mutating them directly.

## Version handle

Each `CTO` carries `last_event_id`, the event ID of the hub-authored event
that most recently produced this canonical state (`cto_created` or
`delta_merged`).

Purposes use `CTOIndex.last_event_id` as provenance when constructing
[Deltas](delta.md), typically by recording it as `based_on_event_id`.

## Content profiles

The `content_profile` field determines the required shape of `content`. The
canonical example profile is `"conversation"`:

```python
content_profile = "conversation"
content = {"speaker": {"id": "user"}, "text": "hello"}
```

Unknown profiles are accepted in v0 but must still provide a dict-like `content`.

## CTOIndex

`CTOIndex` is the lightweight routing reference carried in hub-authored event
payloads. It contains enough information for a Purpose to make routing decisions without loading the full CTO.

Purposes that need full content or observations call
`ttt.librarian.get_cto(turn_id)`.

## Reference

::: turnturnturn.cto.CTO

::: turnturnturn.cto.CTOIndex
