from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class Delta:
    """
    A purpose-proposed change for hub merge.

    Provenance:
      - purpose_name: semantic kind (namespace owner)
      - purpose_id: instance id (who said it)
    """

    delta_id: UUID
    session_id: UUID
    turn_id: UUID

    purpose_name: str
    purpose_id: UUID

    # purpose-owned namespace payload (hub should treat as opaque)
    patch: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "delta_id": str(self.delta_id),
            "session_id": str(self.session_id),
            "turn_id": str(self.turn_id),
            "purpose_name": self.purpose_name,
            "purpose_id": str(self.purpose_id),
            "patch": self.patch,
        }
