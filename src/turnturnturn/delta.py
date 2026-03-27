"""
Delta — a purpose-proposed change for hub merge.

A Delta is the only mechanism by which a Purpose may influence canonical
CTO state. Purposes never write to the CTO directly — they construct a
Delta and submit it to the hub via hub.take_turn(ProposeDelta). The hub validates,
merges, and emits a delta_merged event.

Patch semantics are append-only: all values must be lists. The hub
extends the Purpose's observation namespace with the patch contents;
it never replaces or deletes existing observations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class Delta:
    """
    A purpose-proposed change for hub merge.

    Identifies the target CTO (turn_id), the proposing Purpose (purpose_name
    and purpose_id for namespace ownership and provenance), and the patch
    to apply. The hub validates and merges the patch into the Purpose's
    observation namespace; it never applies the patch directly.

    Patch shape:
        {key: [value, ...], ...}
    All values must be lists — the hub enforces append-only semantics.
    The hub treats patch contents as opaque within the namespace.

    Provenance fields:
        purpose_name: semantic kind, doubles as the observation namespace key.
        purpose_id: instance UUID, distinguishes concurrent instances of the
            same Purpose name.
        based_on_event_id: the last_event_id of the CTO state this Delta was
            derived from. Used for causal reconstruction, replay, and audit.
            None if the proposing Purpose did not record it.
    """

    delta_id: UUID
    session_id: UUID
    turn_id: UUID

    purpose_name: str
    purpose_id: UUID

    # Append-only patch for the purpose_name observation namespace.
    # All values must be lists — enforced by hub at merge time.
    patch: dict[str, Any]

    # The event_id of the cto_started or delta_merged event that produced
    # the CTO state this Delta was derived from. Purposes read this from
    # CTOIndex.last_event_id in the triggering HubEvent payload — no extra
    # get_cto() call needed.
    #
    # Provenance only — not a conflict-detection mechanism. All observations
    # are append-only and namespace-scoped; there are no destructive writes
    # to conflict on. based_on_event_id answers "what canonical state was
    # this Purpose reasoning from?" for causal reconstruction and replay.
    #
    # None if the proposing Purpose did not record which CTO state it was
    # based on (e.g. Purposes written before delta versioning was introduced).
    based_on_event_id: UUID | None = None

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize to a JSON-safe dict for persistence and transport.

        UUIDs are rendered as strings, including based_on_event_id (None if
        absent). patch is expected to be JSON-safe by construction — callers
        are responsible for ensuring this.
        """
        return {
            "delta_id": str(self.delta_id),
            "session_id": str(self.session_id),
            "turn_id": str(self.turn_id),
            "purpose_name": self.purpose_name,
            "purpose_id": str(self.purpose_id),
            "patch": self.patch,
            "based_on_event_id": (
                str(self.based_on_event_id) if self.based_on_event_id else None
            ),
        }
