"""HubEvent, HubEventType, and payload builder helpers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any
from uuid import UUID


class HubEventType(str, Enum):
    """
    Hub-authoritative lifecycle events.

    Naming principle:
      - event_type names what *the hub* has made true
      - avoid receiver-relative terms ("received", "seen", etc.)
    """

    CTO_CREATED = "cto_created"
    DELTA_MERGED = "delta_merged"
    PURPOSE_STARTED = "purpose_started"
    PURPOSE_COMPLETED = "purpose_completed"
    # add TURN_COMPLETED later if needed


@dataclass(frozen=True)
class HubEvent:
    """
    The event envelope.

    `turn_id` is nullable because some events are not scoped to a CTO
    (e.g., purpose registration, session lifecycle).

    `hub_token` is set by the hub at dispatch time to the token assigned
    to the receiving Purpose at registration. BasePurpose.take_turn()
    validates this field before delegating to _handle_event(). It is
    per-recipient — the hub constructs a separate envelope per Purpose
    rather than broadcasting a single shared event object, so tokens
    are never visible across Purpose boundaries.
    """

    event_type: HubEventType
    event_id: UUID
    created_at_ms: int

    session_id: UUID | None = None
    turn_id: UUID | None = None
    payload: dict[str, Any] | None = None

    # Set by hub at dispatch time. Validated by BasePurpose.take_turn().
    # None only in legacy/test contexts where token validation is not active.
    hub_token: str | None = None


def payload_delta_merged(
    *,
    delta_dict: dict[str, Any],
    cto_index_dict: dict[str, Any],
) -> dict[str, Any]:
    """
    Build the payload dict for a delta_merged HubEvent.

    Carries the full serialized Delta for provenance and a CTOIndex dict as
    a lightweight routing reference. Purposes that need full CTO state
    (content, observations) call ttt.librarian.get_cto(turn_id).

    based_on_event_id is recorded in the serialized Delta for causal
    reconstruction and replay — it is provenance, not a conflict signal.
    All observations are append-only and namespace-scoped; there are no
    destructive writes to conflict on.

    Args:
        delta_dict: Serialized Delta from Delta.to_dict().
        cto_index_dict: Serialized CTOIndex from CTOIndex.to_dict().

    Returns:
        A JSON-safe payload dict with _schema "delta_merged" and _v 1.
    """
    return {
        "_schema": "delta_merged",
        "_v": 1,
        "delta": delta_dict,
        "cto_index": cto_index_dict,
    }


def payload_cto_created(
    *,
    cto_index_dict: dict[str, Any],
    submitted_by_purpose_id: str | None = None,
    submitted_by_purpose_name: str | None = None,
    submitted_by_label: str | None = None,
) -> dict[str, Any]:
    """
    Build the payload dict for a cto_created HubEvent.

    Carries a CTOIndex as a lightweight routing reference and optional
    submitter attribution. Purposes that need full CTO state call
    ttt.librarian.get_cto(turn_id). ctoPersistPurpose is the canonical
    consumer: it receives a CTOIndex, calls get_cto(), and persists the
    full canonical state.

    All payloads include _schema (payload type identifier) and _v
    (payload version) for forward-compatibility and deserializer dispatch.
    Submitter attribution fields are all nullable — use submitted_by_label
    for non-Purpose callers (e.g. a direct API client), and the purpose
    fields for Purpose-originated turns.

    Args:
        cto_index_dict: Serialized CTOIndex from CTOIndex.to_dict().
        submitted_by_purpose_id: UUID string of the submitting Purpose, if any.
        submitted_by_purpose_name: Name of the submitting Purpose, if any.
        submitted_by_label: Free-form provenance label for non-Purpose callers.

    Returns:
        A JSON-safe payload dict with _schema "cto_created" and _v 1.
    """
    return {
        "_schema": "cto_created",
        "_v": 1,
        "cto_index": cto_index_dict,
        "submitted_by_purpose_id": submitted_by_purpose_id,
        "submitted_by_purpose_name": submitted_by_purpose_name,
        "submitted_by_label": submitted_by_label,
    }
