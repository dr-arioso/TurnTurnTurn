from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from .cto import CTO, validate_content_profile
from .events import HubEvent, HubEventType, payload_cto_created
from .protocols import PurposeProtocol
from .registry import PurposeRegistration
from .snargle import TurnSnargle

"""
CTO creation boundary:
submit_snargle(TurnSnargle)
    -> validate profile contract
    -> create CTO
    -> emit cto_created {cto: ...}
    -> dispatch purposes (subscription + DAG in later versions)
"""


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class TTT:
    """
    TurnTurnTurn hub runtime.

    Positioning (v0):
      - TTT is the hub: authoritative CTO creation + Delta merge + event emission.
      - Purposes are registered agenda-bearing actors that receive HubEvents.
      - Ingress happens via submit_snargle(); the hub creates CTOs from snargles.
    """

    registrations: dict[UUID, PurposeRegistration]

    @classmethod
    def create(cls) -> "TTT":
        return cls(registrations={})

    async def register_purpose(
        self,
        purpose: PurposeProtocol,
        *,
        subscriptions: list[dict[str, Any]] | None = None,
    ) -> None:
        # v0: in-memory registry only. Later: emit PURPOSE_REGISTERED, persist, auth.
        subs = subscriptions or []
        self.registrations[purpose.id] = PurposeRegistration(
            purpose=purpose,
            token=purpose.token,
            subscriptions=subs,
        )

    async def submit_snargle(self, snargle: TurnSnargle) -> UUID:
        """
        Validate the snargle, create a CTO, emit cto_created, then dispatch.
        Returns the new CTO's turn_id.
        """
        validate_content_profile(snargle.content_profile, snargle.content)

        cto = CTO(
            turn_id=uuid4(),
            session_id=snargle.session_id,
            created_at_ms=now_ms(),
            content_profile=snargle.content_profile,
            content=dict(snargle.content),
        )

        event = HubEvent(
            event_type=HubEventType.CTO_CREATED,
            event_id=uuid4(),
            created_at_ms=now_ms(),
            session_id=cto.session_id,
            turn_id=cto.turn_id,
            payload=payload_cto_created(
                cto_dict=cto.to_dict(),
                submitted_by_label=snargle.submitted_by_label,
            ),
        )

        await self._multicast(event)
        # v0: no DAG yet; dispatch is “all subscribers for this event”
        return cto.turn_id

    async def _multicast(self, event: HubEvent) -> None:
        """
        v0: naive broadcast to all registered purposes.

        Later:
          - subscription matching by event_type (+ filters)
          - DAG eligibility gating
          - persistence via TRTPurpose
        """
        for reg in self.registrations.values():
            await reg.purpose.take_turn(event)
