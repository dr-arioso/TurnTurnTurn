"""
DAG eligibility model for Purpose dispatch.

Placeholder module — not yet implemented.

The DAG layer answers the question: given that a HubEvent has been emitted,
which Purposes are *eligible* to fire right now? Eligibility is distinct from
subscription (interest) — a Purpose may be subscribed to an event but not
yet eligible because its dependencies have not resolved.

Design is deferred until Adjacency integration drives the requirements from
real usage. The working reference implementation is in the Adjacency
dataclasses (DAGNode / DAGStatus), which will inform this layer.

Expected public surface (subject to change):
  - DAGNode: per-Purpose node with dependency set and status state machine
  - DAGStatus: WAITING → ELIGIBLE → DISPATCHED → RESOLVED
  - DAGResolver: hub-facing component that drives status transitions
"""
