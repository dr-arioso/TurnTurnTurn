from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .protocols import PurposeProtocol


@dataclass(frozen=True)
class PurposeRegistration:
    """
    Hub registry record for a Purpose instance.
    """

    purpose: PurposeProtocol

    # token is assigned/managed by hub; purpose.token may be None until assigned
    token: str | None

    # subscriptions are a v0 placeholder; later you’ll likely formalize this
    subscriptions: list[dict[str, Any]]
