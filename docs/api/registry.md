# Registry

`PurposeRegistration` is the hub’s internal record for each registered
Purpose. You do not construct these directly — `TTT.start_purpose()` creates
and stores them.

A registration holds the Purpose object itself plus the hub-issued route
credentials used for Purpose-to-hub submission and hub-to-Purpose delivery.

## Key fields

- `purpose` — the registered Purpose instance
- `token` — hub-issued Purpose token used for authenticated submission
- `downlink_signature` — hub-issued route-integrity token for hub-to-Purpose delivery
- `subscriptions` — current subscription hints for future routing/DAG work

## Reference

::: turnturnturn.registry.PurposeRegistration
