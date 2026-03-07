"""Purpose registration record for the TTT hub registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .protocols import PurposeProtocol


@dataclass(frozen=True)
class PurposeRegistration:
    """
    Hub registry record for a registered Purpose instance.

    Created by ttt.start_purpose() and stored in TTT.registrations,
    keyed by purpose.id.

    The hub consults this record at dispatch time to stamp both the
    per-recipient ingress token and the per-recipient downlink signature
    onto each HubEvent envelope.
    """

    purpose: PurposeProtocol

    # Hub-assigned token for Purpose -> hub ingress authentication.
    token: str | None

    # Hub-issued signature for hub -> Purpose downlink verification.
    downlink_signature: str | None

    # Subscription filter hints. Currently unused in v0 — all registered
    # Purposes receive all events. Will drive subscription matching once
    # the DAG/subscription layer is implemented.
    subscriptions: list[dict[str, Any]]
