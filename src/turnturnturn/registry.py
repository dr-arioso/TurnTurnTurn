"""Purpose registration record for the TTT hub registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .protocols import PurposeProtocol


@dataclass(frozen=True)
class PurposeRegistration:
    """
    Hub registry record for a registered Purpose instance.

    Created by TTT.register_purpose() and stored in TTT.registrations,
    keyed by purpose.id. The hub consults this record at dispatch time
    to stamp hub_token onto each per-recipient HubEvent envelope.
    """

    purpose: PurposeProtocol

    # Hub-assigned token for this registration. Matches the token assigned
    # to the Purpose via BasePurpose._assign_token(). None for raw
    # PurposeProtocol implementors that are not BasePurpose subclasses.
    token: str | None

    # Subscription filter hints. Currently unused in v0 — all registered
    # Purposes receive all events. Will drive subscription matching once
    # the DAG/subscription layer is implemented.
    subscriptions: list[dict[str, Any]]
