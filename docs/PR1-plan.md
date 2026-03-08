I reviewed the relevant source and test files in the uploaded repo before drafting this.

Below is a **copy-paste / search-replace execution plan for the code-layer commits**. This covers:

* source code
* tests
* docstrings/comments in the touched code files

I am **not** including the MkDocs/static-doc patching in this turn; this is the code-and-tests layer only.

---

# Commit 1 — add routing/downlink exceptions and event protocols

## 1. Replace `src/turnturnturn/errors.py` completely

Replace the entire file with:

```python
"""
TTT exception hierarchy.

All TTT-specific exceptions inherit from TTTError so consuming projects can
catch the broad case or specific subtypes as needed.
"""


class TTTError(Exception):
    """Base class for all TTT exceptions."""


class UnauthorizedDispatchError(TTTError):
    """
    Raised when a Purpose-originated event fails hub ingress authentication
    or when a hub-authored event is delivered to a Purpose with invalid
    routing credentials.

    At hub ingress, this means the submitted event's claimed sender does not
    match the registration resolved from hub_token.

    At Purpose downlink, this means take_turn() was called from outside the
    registering hub — either directly by another Purpose or by code that
    fabricated a hub-looking event without going through hub dispatch.
    """


class InvalidDownlinkSignatureError(TTTError):
    """
    Raised when a Purpose rejects a hub-authored event whose
    downlink_signature does not match the signature assigned at registration.

    This is an anti-bypass / route-integrity check. It is intended to catch
    accidental or local architectural violations, not to provide adversarial
    cryptographic security guarantees.
    """


class UnknownEventTypeError(TTTError):
    """
    Raised when hub.take_turn() receives an event_type that has no routing
    rule in the hub ingress table.
    """


class UnboundPurposeError(TTTError):
    """
    Raised when a Purpose that has not been registered with a hub attempts
    to receive a hub-authored event via take_turn().

    A Purpose is unbound if its hub token and downlink signature have not yet
    been assigned by a hub. Register the Purpose with ttt.start_purpose()
    before use.
    """
```

---

## 2. Replace `src/turnturnturn/protocols.py` completely

Replace the entire file with:

```python
"""Structural protocols for TTT participants and event envelopes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable
from uuid import UUID

if TYPE_CHECKING:
    from .events import HubEvent


@runtime_checkable
class EventPayloadProtocol(Protocol):
    """
    Serialization contract for event payload objects.

    All events carry a payload object rather than an ad-hoc dict so the hub
    can rely on a uniform serialization path for logging, persistence, and
    debugging.
    """

    def as_dict(self) -> dict[str, Any]: ...


@runtime_checkable
class EventProtocol(Protocol):
    """
    Minimal event envelope contract shared by hub-authored and
    Purpose-originated events.
    """

    event_type: str
    event_id: UUID
    created_at_ms: int
    payload: EventPayloadProtocol


@runtime_checkable
class PurposeEventProtocol(EventProtocol, Protocol):
    """
    Stricter envelope contract for Purpose-originated ingress events.

    These fields represent a claim of origin. The hub validates that the
    claimed sender matches the registration resolved from hub_token before
    routing the event.
    """

    purpose_id: UUID
    purpose_name: str
    hub_token: str


@runtime_checkable
class TurnTakerProtocol(Protocol):
    """
    A component that can receive hub-authored events.

    NOTE:
    - "TurnTaker" is a capability role (can participate in the event mesh).
    - "Purpose" is the agenda-bearing registered actor (see PurposeProtocol).
    """

    async def take_turn(self, event: HubEvent) -> None: ...


@runtime_checkable
class PurposeProtocol(TurnTakerProtocol, Protocol):
    """
    A registered agenda-bearing actor in the TTT mesh.

    Identification:
      - name: semantic kind ("ca", "embeddingizer", "socratic", ...)
      - id: per-instance UUID (multiple instances can share the same name)
      - token: hub-assigned ingress token, None until registered with a hub.

    BasePurpose is the recommended implementation base — it enforces that
    take_turn() rejects events whose routing credentials do not match the
    values assigned by the hub at registration.

    Raw PurposeProtocol implementors (e.g. simple test doubles) may still be
    registered, but because they do not participate in BasePurpose validation,
    they should be treated as test-only conveniences rather than production
    implementations.
    """

    name: str
    id: UUID
    token: str | None
```

---

# Commit 2 — split `events.py` into `events/` package and normalize payloads

## 3. Delete `src/turnturnturn/events.py`

Delete the file entirely.

---

## 4. Create `src/turnturnturn/events/__init__.py`

Create a new file with exactly this content:

```python
"""Public event and payload surface for hub and Purpose routing."""

from .hub_events import (
    CTOCreatedPayload,
    DeltaMergedPayload,
    EmptyPayload,
    HubEvent,
    HubEventType,
)
from .purpose_events import DeltaProposalEvent, DeltaProposalPayload

__all__ = [
    "CTOCreatedPayload",
    "DeltaMergedPayload",
    "DeltaProposalEvent",
    "DeltaProposalPayload",
    "EmptyPayload",
    "HubEvent",
    "HubEventType",
]
```

---

## 5. Create `src/turnturnturn/events/hub_events.py`

Create a new file with exactly this content:

```python
"""Hub-authored event definitions and payload classes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any
from uuid import UUID

from ..protocols import EventPayloadProtocol


class HubEventType(str, Enum):
    """
    Hub-authoritative lifecycle and routing events.

    Naming principle:
      - event_type names what the hub has made true
      - avoid receiver-relative terms ("received", "seen", etc.)
    """

    CTO_CREATED = "cto_created"
    DELTA_MERGED = "delta_merged"
    DELTA_PROPOSAL = "delta_proposal"
    PURPOSE_STARTED = "purpose_started"
    PURPOSE_COMPLETED = "purpose_completed"


@dataclass(frozen=True)
class EmptyPayload(EventPayloadProtocol):
    """Payload for events that carry no additional structured data."""

    def as_dict(self) -> dict[str, Any]:
        return {}


@dataclass(frozen=True)
class CTOCreatedPayload(EventPayloadProtocol):
    """
    Payload for a cto_created HubEvent.

    Carries a CTOIndex as a lightweight routing reference and optional
    submitter attribution. Purposes that need full CTO state call
    ttt.librarian.get_cto(turn_id).
    """

    cto_index: dict[str, Any]
    submitted_by_purpose_id: str | None = None
    submitted_by_purpose_name: str | None = None
    submitted_by_label: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "_schema": "cto_created",
            "_v": 1,
            "cto_index": self.cto_index,
            "submitted_by_purpose_id": self.submitted_by_purpose_id,
            "submitted_by_purpose_name": self.submitted_by_purpose_name,
            "submitted_by_label": self.submitted_by_label,
        }


@dataclass(frozen=True)
class DeltaMergedPayload(EventPayloadProtocol):
    """
    Payload for a delta_merged HubEvent.

    Carries the full serialized Delta for provenance and a CTOIndex dict as
    a lightweight routing reference. Purposes that need full CTO state call
    ttt.librarian.get_cto(turn_id).
    """

    delta: dict[str, Any]
    cto_index: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "_schema": "delta_merged",
            "_v": 1,
            "delta": self.delta,
            "cto_index": self.cto_index,
        }


@dataclass(frozen=True)
class HubEvent:
    """
    Hub-authored event envelope delivered on the downlink to registered
    Purposes.

    `turn_id` is nullable because some events are not scoped to a CTO
    (e.g., purpose registration, session lifecycle).

    `hub_token` and `downlink_signature` are stamped per-recipient at dispatch
    time. BasePurpose.take_turn() validates both before delegating to
    _handle_event().
    """

    event_type: HubEventType
    event_id: UUID
    created_at_ms: int

    session_id: UUID | None = None
    turn_id: UUID | None = None
    payload: EventPayloadProtocol = EmptyPayload()

    # Set by hub at dispatch time. None only for raw/test recipients that do
    # not participate in BasePurpose validation.
    hub_token: str | None = None
    downlink_signature: str | None = None
```

---

## 6. Create `src/turnturnturn/events/purpose_events.py`

Create a new file with exactly this content:

```python
"""Purpose-originated ingress event definitions."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from ..delta import Delta
from ..protocols import EventPayloadProtocol
from .hub_events import HubEventType


@dataclass(frozen=True)
class DeltaProposalPayload(EventPayloadProtocol):
    """
    Payload for a Purpose-originated delta proposal.

    This is a proposal, not a hub-authored fact. The hub validates the
    submitting Purpose and decides whether and how the proposal becomes
    canonical state.
    """

    delta: Delta

    def as_dict(self) -> dict[str, object]:
        return {"delta": self.delta.to_dict()}


@dataclass(frozen=True)
class DeltaProposalEvent:
    """
    Purpose-originated ingress event used to propose a Delta to the hub.

    The hub validates purpose_id, purpose_name, and hub_token against the
    registration resolved from hub_token before routing the event.
    """

    event_type: HubEventType
    event_id: UUID
    created_at_ms: int
    purpose_id: UUID
    purpose_name: str
    hub_token: str
    payload: DeltaProposalPayload
```

---

# Commit 3 — registration and downlink validation

## 7. Replace `src/turnturnturn/registry.py` completely

Replace the entire file with:

```python
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
```

---

## 8. Replace `src/turnturnturn/base_purpose.py` completely

Replace the entire file with:

```python
"""
BasePurpose — abstract base class for all TTT Purposes.

Consuming projects subclass BasePurpose and implement _handle_event().
The public dispatch entry point (take_turn()) is owned by this base class
and must not be overridden — it validates hub-issued routing credentials
before delegating to _handle_event().

The hub assigns two route credentials at registration time via
ttt.start_purpose():

- token: authenticates Purpose -> hub ingress
- downlink_signature: verifies hub -> Purpose downlink routing

Until registered, the Purpose is unbound and take_turn() raises
UnboundPurposeError. After registration, only HubEvents carrying both the
matching hub_token and matching downlink_signature are accepted.

This design closes the point-to-point bypass: because take_turn() validates
hub-issued route credentials, a Purpose cannot receive hub-looking events
from any source other than the hub that registered it.

Subclass contract:
  - Implement _handle_event(event) for domain logic.
  - Do not override take_turn().
  - Pass name and id to super().__init__() or set them as class attributes.
  - Do not set _token or _downlink_signature directly — both are assigned
    exclusively by the hub.
"""

from __future__ import annotations

import abc
from uuid import UUID

from .errors import (
    InvalidDownlinkSignatureError,
    UnauthorizedDispatchError,
    UnboundPurposeError,
)
from .events import HubEvent

_UNBOUND = object()


class BasePurpose(abc.ABC):
    """
    Abstract base class for TTT Purposes.

    Implements the TurnTakerProtocol / PurposeProtocol contract with
    hub-issued route validation built in. Subclasses implement
    _handle_event() for domain logic and must not override take_turn().
    """

    name: str
    id: UUID

    def __init__(self) -> None:
        """Initialise the base Purpose in unbound state."""
        self._token: object = _UNBOUND
        self._downlink_signature: object = _UNBOUND

    @property
    def token(self) -> str | None:
        """
        The hub-assigned ingress token for this Purpose instance.

        None until registered with a hub. After registration, always a
        non-empty string. Never set this directly — use ttt.start_purpose().
        """
        if self._token is _UNBOUND:
            return None
        return self._token  # type: ignore[return-value]

    @property
    def downlink_signature(self) -> str | None:
        """
        The hub-issued downlink signature for this Purpose instance.

        None until registered with a hub. After registration, always a
        non-empty string for BasePurpose subclasses.
        """
        if self._downlink_signature is _UNBOUND:
            return None
        return self._downlink_signature  # type: ignore[return-value]

    def _assign_token(self, token: str) -> None:
        """
        Assign the hub ingress token. Called exclusively by ttt.start_purpose().
        """
        if not token:
            raise ValueError("hub token must be a non-empty string")
        self._token = token

    def _assign_downlink_signature(self, downlink_signature: str) -> None:
        """
        Assign the hub-issued downlink signature.

        Called exclusively by ttt.start_purpose().
        """
        if not downlink_signature:
            raise ValueError("downlink signature must be a non-empty string")
        self._downlink_signature = downlink_signature

    async def take_turn(self, event: HubEvent) -> None:
        """
        Validate hub-issued routing credentials and delegate to _handle_event().

        This is the hub-facing downlink entry point. It must not be overridden
        by subclasses — override _handle_event() instead.

        Validates that:
          1. This Purpose has been registered with a hub.
          2. The event carries a token matching this Purpose's token.
          3. The event carries a downlink_signature matching this Purpose's
             assigned signature.
        """
        if self._token is _UNBOUND or self._downlink_signature is _UNBOUND:
            raise UnboundPurposeError(
                f"Purpose {self.name!r} (id={self.id}) has not been registered "
                f"with a hub. Call ttt.start_purpose() before dispatch."
            )

        if event.hub_token != self._token:
            raise UnauthorizedDispatchError(
                f"Purpose {self.name!r} (id={self.id}) rejected event "
                f"{event.event_id} — hub token mismatch."
            )

        if event.downlink_signature != self._downlink_signature:
            raise InvalidDownlinkSignatureError(
                f"Purpose {self.name!r} (id={self.id}) rejected event "
                f"{event.event_id} — downlink signature mismatch."
            )

        await self._handle_event(event)

    @abc.abstractmethod
    async def _handle_event(self, event: HubEvent) -> None:
        """
        Handle a validated HubEvent. Implement domain logic here.

        Called by take_turn() after hub-issued routing validation passes.
        """
```

---

# Commit 4 — hub ingress, `take_turn()`, and internalized delta merge

## 9. In `src/turnturnturn/hub.py`, replace the import block

Find this exact block:

```python
import secrets
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from .base_purpose import BasePurpose
from .cto import CTO
from .delta import Delta
from .events import HubEvent, HubEventType, payload_cto_created, payload_delta_merged
from .profile import ProfileRegistry
from .protocols import PurposeProtocol
from .registry import PurposeRegistration
```

Replace it with:

```python
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from .base_purpose import BasePurpose
from .cto import CTO
from .delta import Delta
from .errors import UnknownEventTypeError, UnauthorizedDispatchError
from .events import (
    CTOCreatedPayload,
    DeltaMergedPayload,
    DeltaProposalEvent,
    HubEvent,
    HubEventType,
)
from .profile import ProfileRegistry
from .protocols import PurposeEventProtocol, PurposeProtocol
from .registry import PurposeRegistration
```

---

## 10. In `src/turnturnturn/hub.py`, add the hub secret field

Find this exact block inside `class TTT`:

```python
    _ctos: dict[UUID, CTO] = field(default_factory=dict, init=False, repr=False)
    librarian: Librarian = field(init=False, repr=False)
```

Replace it with:

```python
    _ctos: dict[UUID, CTO] = field(default_factory=dict, init=False, repr=False)
    _hub_secret: str = field(default_factory=lambda: secrets.token_hex(32), repr=False)
    librarian: Librarian = field(init=False, repr=False)
```

---

## 11. In `src/turnturnturn/hub.py`, insert `_build_downlink_signature()` and `_resolve_registration_for_token()`

Insert the following methods **immediately after** the existing `_session_context()` method:

```python
    def _build_downlink_signature(self, token: str, purpose_id: UUID) -> str:
        """
        Derive a per-hub-instance, per-Purpose downlink signature.

        This is an anti-bypass / route-integrity check, not a claim of
        adversarial cryptographic security.
        """
        message = f"{token}:{purpose_id}".encode("utf-8")
        return hmac.new(
            self._hub_secret.encode("utf-8"),
            message,
            hashlib.sha256,
        ).hexdigest()

    def _resolve_registration_for_token(self, token: str) -> PurposeRegistration:
        """
        Resolve a registration from a hub-issued ingress token.

        Raises:
            UnauthorizedDispatchError: If the token does not resolve to
                exactly one current registration.
        """
        matches = [reg for reg in self.registrations.values() if reg.token == token]
        if len(matches) != 1:
            raise UnauthorizedDispatchError(
                "Purpose-originated event rejected — invalid hub token."
            )
        return matches[0]
```

---

## 12. In `src/turnturnturn/hub.py`, replace `start_purpose()`

Find the entire existing `start_purpose()` method beginning with:

```python
    async def start_purpose(
```

and ending with the line:

```python
        self.registrations[purpose.id] = PurposeRegistration(
            purpose=purpose,
            token=token,
            subscriptions=subs,
        )
```

Replace that entire method with:

```python
    async def start_purpose(
        self,
        purpose: PurposeProtocol,
        *,
        subscriptions: list[dict[str, Any]] | None = None,
    ) -> None:
        """
        Bootstrap a Purpose into the hub and assign its route credentials.

        start_purpose() stands outside the event model because no authenticated
        ingress event can exist until the Purpose has been registered.

        BasePurpose instances receive two hub-issued credentials:

        - token: authenticates Purpose -> hub ingress
        - downlink_signature: verifies hub -> Purpose downlink routing

        Raw PurposeProtocol implementors may still be registered for tests, but
        they do not participate in BasePurpose route validation.
        """
        token: str | None = None
        downlink_signature: str | None = None

        if isinstance(purpose, BasePurpose):
            token = secrets.token_hex(16)
            downlink_signature = self._build_downlink_signature(token, purpose.id)
            purpose._assign_token(token)
            purpose._assign_downlink_signature(downlink_signature)

        subs = subscriptions or []
        self.registrations[purpose.id] = PurposeRegistration(
            purpose=purpose,
            token=token,
            downlink_signature=downlink_signature,
            subscriptions=subs,
        )
```

---

## 13. In `src/turnturnturn/hub.py`, replace the `payload=` in `start_turn()`

Find this exact block:

```python
            payload=payload_cto_created(
                cto_index_dict=cto.to_index().to_dict(),
                submitted_by_label=submitted_by_label,
            ),
```

Replace it with:

```python
            payload=CTOCreatedPayload(
                cto_index=cto.to_index().to_dict(),
                submitted_by_label=submitted_by_label,
            ),
```

---

## 14. In `src/turnturnturn/hub.py`, replace `merge_delta()` with `take_turn()`, `_validate_purpose_event()`, and `_merge_delta()`

Find the entire existing method beginning with:

```python
    async def merge_delta(self, delta: Delta) -> UUID:
```

and ending with:

```python
        await self._multicast(event)
        return delta_merged_event_id
```

Replace that entire block with:

```python
    def _validate_purpose_event(
        self, event: PurposeEventProtocol
    ) -> tuple[PurposeRegistration, Delta]:
        """
        Validate a Purpose-originated event and return its registration and Delta.

        Validation rules:
          1. hub_token resolves to exactly one current registration
          2. purpose_id matches that registration
          3. purpose_name matches that registration
        """
        reg = self._resolve_registration_for_token(event.hub_token)

        if event.purpose_id != reg.purpose.id:
            raise UnauthorizedDispatchError(
                "Purpose-originated event rejected — purpose_id does not match "
                "the registration resolved from hub_token."
            )

        if event.purpose_name != reg.purpose.name:
            raise UnauthorizedDispatchError(
                "Purpose-originated event rejected — purpose_name does not match "
                "the registration resolved from hub_token."
            )

        delta = event.payload.delta
        return reg, delta

    async def take_turn(self, event: PurposeEventProtocol) -> UUID:
        """
        Canonical ingress path for Purpose-originated events.

        The hub validates the claimed sender against the registration
        resolved from hub_token, then routes by event_type.
        """
        if event.event_type is HubEventType.DELTA_PROPOSAL:
            _reg, delta = self._validate_purpose_event(event)
            return await self._merge_delta(delta)

        raise UnknownEventTypeError(
            f"hub.take_turn: unsupported event_type {event.event_type!r}"
        )

    async def _merge_delta(self, delta: Delta) -> UUID:
        """
        Validate and merge a Purpose-proposed Delta into canonical CTO state.

        This is a hub-internal mutation helper. Purposes submit proposals via
        hub.take_turn(); validated ingress routing calls _merge_delta().
        """
        cto = self._ctos.get(delta.turn_id)
        if cto is None:
            raise KeyError(f"_merge_delta: unknown turn_id {delta.turn_id!r}")

        for key, val in delta.patch.items():
            if not isinstance(val, list):
                raise ValueError(
                    f"_merge_delta: patch[{key!r}] must be a list, "
                    f"got {type(val).__name__!r} — hub enforces append-only semantics"
                )

        delta_merged_event_id = uuid4()

        namespace = delta.purpose_name
        existing_obs = dict(cto.observations)
        existing_ns = list(existing_obs.get(namespace, []))
        for key, items in delta.patch.items():
            existing_ns.extend({"key": key, "value": v} for v in items)
        existing_obs[namespace] = existing_ns

        updated_cto = CTO(
            turn_id=cto.turn_id,
            session_id=cto.session_id,
            created_at_ms=cto.created_at_ms,
            content_profile=cto.content_profile,
            content=cto.content,
            observations=existing_obs,
            last_event_id=delta_merged_event_id,
        )
        self._ctos[updated_cto.turn_id] = updated_cto

        event = HubEvent(
            event_type=HubEventType.DELTA_MERGED,
            event_id=delta_merged_event_id,
            created_at_ms=now_ms(),
            session_id=updated_cto.session_id,
            turn_id=updated_cto.turn_id,
            payload=DeltaMergedPayload(
                delta=delta.to_dict(),
                cto_index=updated_cto.to_index().to_dict(),
            ),
        )
        await self._multicast(event)
        return delta_merged_event_id
```

---

## 15. In `src/turnturnturn/hub.py`, replace `_multicast()`

Find the entire existing `_multicast()` method beginning with:

```python
    async def _multicast(self, event: HubEvent) -> None:
```

and ending with:

```python
            await reg.purpose.take_turn(addressed)
```

Replace it with:

```python
    async def _multicast(self, event: HubEvent) -> None:
        """
        Broadcast a hub-authored event to all registered Purposes.

        Constructs a per-recipient envelope for each Purpose, stamping both
        hub_token and downlink_signature with the route credentials assigned
        at registration time.

        v0: naive broadcast — every registered Purpose receives every event.
        """
        for reg in self.registrations.values():
            addressed = HubEvent(
                event_type=event.event_type,
                event_id=event.event_id,
                created_at_ms=event.created_at_ms,
                session_id=event.session_id,
                turn_id=event.turn_id,
                payload=event.payload,
                hub_token=reg.token,
                downlink_signature=reg.downlink_signature,
            )
            await reg.purpose.take_turn(addressed)
```

---

# Commit 5 — package exports and test fixtures

## 16. Replace `tests/conftest.py` completely

Replace the entire file with:

```python
"""Shared fixtures and configuration for the TTT test suite."""

from __future__ import annotations

from uuid import uuid4

import pytest

from turnturnturn import BasePurpose, TTT
from turnturnturn.events import HubEvent

pytest_plugins = ("pytest_asyncio",)


class RecordingPurpose(BasePurpose):
    """A BasePurpose subclass that records every event it receives."""

    name = "recording"

    def __init__(self) -> None:
        super().__init__()
        self.id = uuid4()
        self.received: list[HubEvent] = []

    async def _handle_event(self, event: HubEvent) -> None:
        self.received.append(event)


class NamedPurpose(BasePurpose):
    """A BasePurpose subclass with a configurable name."""

    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name
        self.id = uuid4()
        self.received: list[HubEvent] = []

    async def _handle_event(self, event: HubEvent) -> None:
        self.received.append(event)


@pytest.fixture
def hub() -> TTT:
    return TTT.start()


@pytest.fixture
def session_id():
    return uuid4()


@pytest.fixture
def minimal_content() -> dict:
    return {"speaker": {"id": "usr_test"}, "text": "hello"}


@pytest.fixture
def full_content() -> dict:
    return {
        "speaker": {"id": "usr_test", "role": "user", "label": "Tester"},
        "text": "hello",
    }
```

---

## 17. Replace `tests/test_events.py` completely

Replace the entire file with:

```python
"""Tests for the typed event and payload model."""

from __future__ import annotations

from uuid import uuid4

import pytest

from turnturnturn.delta import Delta
from turnturnturn.events import (
    CTOCreatedPayload,
    DeltaMergedPayload,
    DeltaProposalEvent,
    DeltaProposalPayload,
    EmptyPayload,
    HubEvent,
    HubEventType,
)


def _minimal_cto_index_dict() -> dict:
    return {
        "turn_id": str(uuid4()),
        "session_id": str(uuid4()),
        "content_profile": {"id": "conversation", "version": 1},
        "created_at_ms": 0,
    }


def test_event_type_cto_created_value():
    assert HubEventType.CTO_CREATED.value == "cto_created"


def test_event_type_delta_merged_value():
    assert HubEventType.DELTA_MERGED.value == "delta_merged"


def test_event_type_delta_proposal_value():
    assert HubEventType.DELTA_PROPOSAL.value == "delta_proposal"


def test_hub_event_fields():
    eid = uuid4()
    sid = uuid4()
    payload = EmptyPayload()
    event = HubEvent(
        event_type=HubEventType.CTO_CREATED,
        event_id=eid,
        created_at_ms=999,
        session_id=sid,
        payload=payload,
        hub_token="tok",
        downlink_signature="sig",
    )
    assert event.event_type == HubEventType.CTO_CREATED
    assert event.event_id == eid
    assert event.created_at_ms == 999
    assert event.session_id == sid
    assert event.payload is payload
    assert event.hub_token == "tok"
    assert event.downlink_signature == "sig"


def test_hub_event_is_frozen():
    event = HubEvent(
        event_type=HubEventType.CTO_CREATED,
        event_id=uuid4(),
        created_at_ms=0,
    )
    with pytest.raises((AttributeError, TypeError)):
        event.hub_token = "mutated"  # type: ignore[misc]


def test_empty_payload_serializes_to_empty_dict():
    assert EmptyPayload().as_dict() == {}


def test_cto_created_payload_as_dict():
    payload = CTOCreatedPayload(cto_index=_minimal_cto_index_dict())
    data = payload.as_dict()
    assert data["_schema"] == "cto_created"
    assert data["_v"] == 1
    assert "cto_index" in data


def test_delta_merged_payload_as_dict():
    payload = DeltaMergedPayload(
        delta={"delta_id": str(uuid4()), "patch": {"x": [1]}},
        cto_index=_minimal_cto_index_dict(),
    )
    data = payload.as_dict()
    assert data["_schema"] == "delta_merged"
    assert data["_v"] == 1
    assert "delta" in data
    assert "cto_index" in data


def test_delta_proposal_payload_as_dict():
    delta = Delta(
        delta_id=uuid4(),
        session_id=uuid4(),
        turn_id=uuid4(),
        purpose_name="tester",
        purpose_id=uuid4(),
        patch={"x": ["y"]},
    )
    payload = DeltaProposalPayload(delta=delta)
    assert payload.as_dict()["delta"]["purpose_name"] == "tester"


def test_delta_proposal_event_fields():
    pid = uuid4()
    delta = Delta(
        delta_id=uuid4(),
        session_id=uuid4(),
        turn_id=uuid4(),
        purpose_name="tester",
        purpose_id=pid,
        patch={"x": ["y"]},
    )
    payload = DeltaProposalPayload(delta=delta)
    event = DeltaProposalEvent(
        event_type=HubEventType.DELTA_PROPOSAL,
        event_id=uuid4(),
        created_at_ms=123,
        purpose_id=pid,
        purpose_name="tester",
        hub_token="tok",
        payload=payload,
    )
    assert event.event_type == HubEventType.DELTA_PROPOSAL
    assert event.purpose_id == pid
    assert event.purpose_name == "tester"
    assert event.hub_token == "tok"
    assert event.payload is payload
```

---

## 18. Replace `tests/test_base_purpose.py` completely

Replace the entire file with:

```python
"""Tests for BasePurpose routing validation."""

from __future__ import annotations

from uuid import uuid4

import pytest
from conftest import RecordingPurpose

from turnturnturn.errors import (
    InvalidDownlinkSignatureError,
    UnauthorizedDispatchError,
    UnboundPurposeError,
)
from turnturnturn.events import EmptyPayload, HubEvent, HubEventType


def _make_event(
    *,
    hub_token: str | None = None,
    downlink_signature: str | None = None,
) -> HubEvent:
    return HubEvent(
        event_type=HubEventType.CTO_CREATED,
        event_id=uuid4(),
        created_at_ms=0,
        payload=EmptyPayload(),
        hub_token=hub_token,
        downlink_signature=downlink_signature,
    )


def test_token_property_none_before_assignment():
    p = RecordingPurpose()
    assert p.token is None


def test_downlink_signature_property_none_before_assignment():
    p = RecordingPurpose()
    assert p.downlink_signature is None


def test_assign_token_sets_token():
    p = RecordingPurpose()
    p._assign_token("abc123")
    assert p.token == "abc123"


def test_assign_downlink_signature_sets_signature():
    p = RecordingPurpose()
    p._assign_downlink_signature("sig123")
    assert p.downlink_signature == "sig123"


@pytest.mark.asyncio
async def test_take_turn_raises_unbound_when_no_route_credentials():
    p = RecordingPurpose()
    event = _make_event(hub_token=None, downlink_signature=None)
    with pytest.raises(UnboundPurposeError):
        await p.take_turn(event)


@pytest.mark.asyncio
async def test_take_turn_raises_unauthorized_on_wrong_token():
    p = RecordingPurpose()
    p._assign_token("correct_token")
    p._assign_downlink_signature("sig")
    event = _make_event(hub_token="wrong_token", downlink_signature="sig")
    with pytest.raises(UnauthorizedDispatchError):
        await p.take_turn(event)


@pytest.mark.asyncio
async def test_take_turn_raises_invalid_downlink_signature_on_wrong_signature():
    p = RecordingPurpose()
    p._assign_token("tok")
    p._assign_downlink_signature("correct_sig")
    event = _make_event(hub_token="tok", downlink_signature="wrong_sig")
    with pytest.raises(InvalidDownlinkSignatureError):
        await p.take_turn(event)


@pytest.mark.asyncio
async def test_take_turn_calls_handle_event_on_valid_route_credentials():
    p = RecordingPurpose()
    p._assign_token("good_token")
    p._assign_downlink_signature("good_sig")
    event = _make_event(hub_token="good_token", downlink_signature="good_sig")
    await p.take_turn(event)
    assert len(p.received) == 1
    assert p.received[0] is event
```

---

# Commit 6 — hub ingress tests and merge migration

## 19. Create `tests/test_hub_take_turn.py`

Create a new file with exactly this content:

```python
"""Tests for Purpose-originated hub ingress via hub.take_turn()."""

from __future__ import annotations

from uuid import uuid4

import pytest
from conftest import RecordingPurpose

from turnturnturn.delta import Delta
from turnturnturn.errors import UnknownEventTypeError, UnauthorizedDispatchError
from turnturnturn.events import DeltaProposalEvent, DeltaProposalPayload, HubEventType


def _make_delta(*, session_id, turn_id, purpose_name, purpose_id, patch):
    return Delta(
        delta_id=uuid4(),
        session_id=session_id,
        turn_id=turn_id,
        purpose_name=purpose_name,
        purpose_id=purpose_id,
        patch=patch,
    )


def _make_delta_proposal_event(*, purpose, delta):
    return DeltaProposalEvent(
        event_type=HubEventType.DELTA_PROPOSAL,
        event_id=uuid4(),
        created_at_ms=0,
        purpose_id=purpose.id,
        purpose_name=purpose.name,
        hub_token=purpose.token,
        payload=DeltaProposalPayload(delta=delta),
    )


@pytest.mark.asyncio
async def test_take_turn_valid_delta_proposal_updates_observations(
    hub, session_id, minimal_content
):
    purpose = RecordingPurpose()
    await hub.start_purpose(purpose)

    turn_id = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )

    delta = _make_delta(
        session_id=session_id,
        turn_id=turn_id,
        purpose_name=purpose.name,
        purpose_id=purpose.id,
        patch={"tags": ["important"]},
    )
    event = _make_delta_proposal_event(purpose=purpose, delta=delta)

    await hub.take_turn(event)

    cto = hub.librarian.get_cto(turn_id)
    assert purpose.name in cto.observations
    assert any(obs["value"] == "important" for obs in cto.observations[purpose.name])


@pytest.mark.asyncio
async def test_take_turn_wrong_token_raises(hub, session_id, minimal_content):
    purpose = RecordingPurpose()
    await hub.start_purpose(purpose)

    turn_id = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )

    delta = _make_delta(
        session_id=session_id,
        turn_id=turn_id,
        purpose_name=purpose.name,
        purpose_id=purpose.id,
        patch={"x": ["v"]},
    )

    event = DeltaProposalEvent(
        event_type=HubEventType.DELTA_PROPOSAL,
        event_id=uuid4(),
        created_at_ms=0,
        purpose_id=purpose.id,
        purpose_name=purpose.name,
        hub_token="wrong_token",
        payload=DeltaProposalPayload(delta=delta),
    )

    with pytest.raises(UnauthorizedDispatchError):
        await hub.take_turn(event)


@pytest.mark.asyncio
async def test_take_turn_mismatched_purpose_name_raises(hub, session_id, minimal_content):
    purpose = RecordingPurpose()
    await hub.start_purpose(purpose)

    turn_id = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )

    delta = _make_delta(
        session_id=session_id,
        turn_id=turn_id,
        purpose_name=purpose.name,
        purpose_id=purpose.id,
        patch={"x": ["v"]},
    )

    event = DeltaProposalEvent(
        event_type=HubEventType.DELTA_PROPOSAL,
        event_id=uuid4(),
        created_at_ms=0,
        purpose_id=purpose.id,
        purpose_name="not_recording",
        hub_token=purpose.token,
        payload=DeltaProposalPayload(delta=delta),
    )

    with pytest.raises(UnauthorizedDispatchError):
        await hub.take_turn(event)


@pytest.mark.asyncio
async def test_take_turn_unknown_event_type_raises(hub, session_id, minimal_content):
    purpose = RecordingPurpose()
    await hub.start_purpose(purpose)

    turn_id = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )

    delta = _make_delta(
        session_id=session_id,
        turn_id=turn_id,
        purpose_name=purpose.name,
        purpose_id=purpose.id,
        patch={"x": ["v"]},
    )

    event = DeltaProposalEvent(
        event_type=HubEventType.CTO_CREATED,
        event_id=uuid4(),
        created_at_ms=0,
        purpose_id=purpose.id,
        purpose_name=purpose.name,
        hub_token=purpose.token,
        payload=DeltaProposalPayload(delta=delta),
    )

    with pytest.raises(UnknownEventTypeError):
        await hub.take_turn(event)
```

---

## 20. In `tests/test_hub.py`, update the module docstring

Find this exact top block:

```python
"""Tests for the TTT hub runtime (hub.py).

Coverage areas:
  - TTT.start() — profile loading, strict flag
  - start_purpose() — token assignment, re-registration
  - start_turn() — CTO creation, profile validation, event emission, dispatch
  - merge_delta() — append-only merge, unknown turn_id, bad patch shape
  - ttt.librarian.get_cto() — read path, returns None for unknown turn_id
  - _multicast() — per-recipient token stamping, all registered purposes receive event
"""
```

Replace it with:

```python
"""Tests for the TTT hub runtime (hub.py).

Coverage areas:
  - TTT.start() — profile loading, strict flag
  - start_purpose() — token/downlink assignment, re-registration
  - start_turn() — CTO creation, profile validation, event emission, dispatch
  - _merge_delta() via hub.take_turn() — append-only merge and event emission
  - ttt.librarian.get_cto() — read path, returns None for unknown turn_id
  - _multicast() — per-recipient route credential stamping
"""
```

---

## 21. In `tests/test_hub.py`, replace the imports

Find this exact import block:

```python
from turnturnturn import CTO, TTT, Delta
from turnturnturn.errors import UnauthorizedDispatchError
from turnturnturn.events import HubEventType
```

Replace it with:

```python
from turnturnturn import CTO, TTT, Delta
from turnturnturn.errors import InvalidDownlinkSignatureError, UnauthorizedDispatchError
from turnturnturn.events import DeltaProposalEvent, DeltaProposalPayload, HubEventType
```

---

## 22. In `tests/test_hub.py`, add a helper right below the imports

Insert this block **immediately after** the imports:

```python
def _proposal_event_for(delta: Delta, purpose) -> DeltaProposalEvent:
    return DeltaProposalEvent(
        event_type=HubEventType.DELTA_PROPOSAL,
        event_id=uuid4(),
        created_at_ms=0,
        purpose_id=purpose.id,
        purpose_name=purpose.name,
        hub_token=purpose.token,
        payload=DeltaProposalPayload(delta=delta),
    )
```

---

## 23. In `tests/test_hub.py`, update the `start_purpose()` tests

### 23a. In `test_start_purpose_assigns_token`

After:

```python
    assert isinstance(p.token, str)
    assert len(p.token) > 0
```

add:

```python
    assert p.downlink_signature is not None
    assert isinstance(p.downlink_signature, str)
    assert len(p.downlink_signature) > 0
```

---

### 23b. In `test_start_multiple_purposes_each_gets_unique_token`

After:

```python
    assert p1.token != p2.token
```

add:

```python
    assert p1.downlink_signature != p2.downlink_signature
```

---

### 23c. In `test_restart_purpose_issues_new_token`

Replace the entire function body with:

```python
    p = RecordingPurpose()
    await hub.start_purpose(p)
    first_token = p.token
    first_signature = p.downlink_signature

    await hub.start_purpose(p)

    assert p.token != first_token
    assert p.downlink_signature != first_signature
```

---

## 24. In `tests/test_hub.py`, update payload assertions from dict access to `.as_dict()`

### 24a. Find this exact block in `test_start_turn_event_payload_contains_cto_index`:

```python
    event = p.received[0]
    cto_index = event.payload["cto_index"]
```

Replace it with:

```python
    event = p.received[0]
    cto_index = event.payload.as_dict()["cto_index"]
```

---

### 24b. Find this exact block in `test_start_turn_event_does_not_carry_full_cto`:

```python
    payload = p.received[0].payload
    assert "content" not in payload
    assert "observations" not in payload
    assert "cto_index" in payload
```

Replace it with:

```python
    payload = p.received[0].payload.as_dict()
    assert "content" not in payload
    assert "observations" not in payload
    assert "cto_index" in payload
```

---

## 25. In `tests/test_hub.py`, migrate the librarian merge test to `hub.take_turn()`

Find the entire test function:

```python
@pytest.mark.asyncio
async def test_librarian_get_cto_returns_latest_state_after_merge(
    hub, session_id, minimal_content
):
    """librarian.get_cto() must reflect the post-merge CTO, not the original."""
    turn_id = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )
    delta = Delta(
        delta_id=uuid4(),
        session_id=session_id,
        turn_id=turn_id,
        purpose_name="tester",
        purpose_id=uuid4(),
        patch={"tags": ["important"]},
    )
    await hub.merge_delta(delta)
    cto = hub.librarian.get_cto(turn_id)
    assert "tester" in cto.observations
    assert any(obs["value"] == "important" for obs in cto.observations["tester"])
```

Replace it with:

```python
@pytest.mark.asyncio
async def test_librarian_get_cto_returns_latest_state_after_merge(
    hub, session_id, minimal_content
):
    """librarian.get_cto() must reflect the post-merge CTO, not the original."""
    purpose = NamedPurpose("tester")
    await hub.start_purpose(purpose)

    turn_id = await hub.start_turn(
        session_id=session_id,
        content_profile="conversation",
        content=minimal_content,
    )
    delta = Delta(
        delta_id=uuid4(),
        session_id=session_id,
        turn_id=turn_id,
        purpose_name=purpose.name,
        purpose_id=purpose.id,
        patch={"tags": ["important"]},
    )
    await hub.take_turn(_proposal_event_for(delta, purpose))
    cto = hub.librarian.get_cto(turn_id)
    assert "tester" in cto.observations
    assert any(obs["value"] == "important" for obs in cto.observations["tester"])
```

---

## 26. In `tests/test_hub.py`, replace the entire `merge_delta()` section header

Find:

```python
# ---------------------------------------------------------------------------
# merge_delta()
# ---------------------------------------------------------------------------
```

Replace with:

```python
# ---------------------------------------------------------------------------
# _merge_delta() via hub.take_turn()
# ---------------------------------------------------------------------------
```

---

## 27. In `tests/test_hub.py`, replace every `await hub.merge_delta(...)` call

Do this as a **manual targeted replace**, not a blind global replace.

Use this pattern:

### Whenever you currently have:

```python
    await hub.merge_delta(
        Delta(
            ...
            purpose_name="p",
            purpose_id=uuid4(),
            ...
        )
    )
```

replace it with:

```python
    purpose = NamedPurpose("p")
    await hub.start_purpose(purpose)

    delta = Delta(
        ...
        purpose_name=purpose.name,
        purpose_id=purpose.id,
        ...
    )
    await hub.take_turn(_proposal_event_for(delta, purpose))
```

For tests already using a registered `RecordingPurpose`, reuse that registered Purpose rather than creating a new one.

### Specific tests to update this way:

* `test_merge_delta_returns_event_id`
* `test_merge_delta_appends_observations`
* `test_merge_delta_does_not_overwrite_prior_observations`
* `test_merge_delta_namespaces_are_isolated`
* `test_merge_delta_emits_delta_merged_event`
* `test_merge_delta_event_payload_contains_cto_index`
* `test_merge_delta_payload_has_no_stale_delta_field`
* `test_merge_delta_unknown_turn_id_raises`
* `test_merge_delta_non_list_patch_value_raises`

---

## 28. In `tests/test_hub.py`, update the delta-merged payload assertions

Whenever you see:

```python
    payload = p.received[0].payload
```

for a `DELTA_MERGED` event, replace it with:

```python
    payload = p.received[0].payload.as_dict()
```

That applies at least to:

* `test_merge_delta_event_payload_contains_cto_index`
* `test_merge_delta_payload_has_no_stale_delta_field`

---

## 29. In `tests/test_hub.py`, strengthen the multicast credential tests

### 29a. In `test_multicast_stamps_correct_token_per_recipient`, after:

```python
    assert p1.received[0].hub_token != p2.received[0].hub_token
```

add:

```python
    assert p1.received[0].downlink_signature == p1.downlink_signature
    assert p2.received[0].downlink_signature == p2.downlink_signature
    assert p1.received[0].downlink_signature != p2.received[0].downlink_signature
```

---

### 29b. In `test_multicast_token_from_one_purpose_rejected_by_another`, replace the final `with pytest.raises(...)` block

Find:

```python
    with pytest.raises(UnauthorizedDispatchError):
        await p2.take_turn(event_for_p1)
```

Replace it with:

```python
    with pytest.raises((UnauthorizedDispatchError, InvalidDownlinkSignatureError)):
        await p2.take_turn(event_for_p1)
```

---

# Commit 7 — package exports

## 30. Replace `src/turnturnturn/__init__.py` completely

Your current `__init__.py` is not exporting the actual runtime surface. Replace the entire file with:

```python
"""Public package surface for TurnTurnTurn."""

from .base_purpose import BasePurpose
from .cto import CTO
from .delta import Delta
from .errors import (
    InvalidDownlinkSignatureError,
    TTTError,
    UnauthorizedDispatchError,
    UnboundPurposeError,
    UnknownEventTypeError,
)
from .events import (
    CTOCreatedPayload,
    DeltaMergedPayload,
    DeltaProposalEvent,
    DeltaProposalPayload,
    EmptyPayload,
    HubEvent,
    HubEventType,
)
from .hub import TTT
from .protocols import EventPayloadProtocol, EventProtocol, PurposeEventProtocol

__all__ = [
    "BasePurpose",
    "CTO",
    "CTOCreatedPayload",
    "Delta",
    "DeltaMergedPayload",
    "DeltaProposalEvent",
    "DeltaProposalPayload",
    "EmptyPayload",
    "EventPayloadProtocol",
    "EventProtocol",
    "HubEvent",
    "HubEventType",
    "InvalidDownlinkSignatureError",
    "PurposeEventProtocol",
    "TTT",
    "TTTError",
    "UnauthorizedDispatchError",
    "UnboundPurposeError",
    "UnknownEventTypeError",
]
```

---

# Test run after these commits

Run this after Commit 7:

```bash
pytest tests/test_events.py tests/test_base_purpose.py tests/test_hub_take_turn.py tests/test_hub.py
```

Then run the whole suite:

```bash
pytest
```

---

# Important note before you paste Commit 6 changes into `tests/test_hub.py`

That file is the one place where a blind search/replace will create garbage. For that file, use the exact targeted replacements above, especially for the old `await hub.merge_delta(...)` calls.

The source files are straightforward enough to paste as given.

The next sensible turn is for me to give you the same level of **exact copy-paste instructions for the remaining docs-as-code layer**:

* code docstring touchups not already embedded
* `docs/ttt_architecture_v0_18.md` verification
* `docs/dev-guide.md`
* `docs/index.md`
* recommended new `docs/event-flow.md`
* `mkdocs.yml` nav change if present
