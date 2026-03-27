"""Canonical CTO JSON document helpers for import, fixtures, and export."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .cto import CTO

CTO_JSON_SCHEMA = "ttt.cto"
CTO_JSON_VERSION = 1
TTT_PROVENANCE_NAMESPACE = "turnturnturn.provenance"


@dataclass(frozen=True)
class NormalizedImportedCTO:
    """Normalized import-ready view of a canonical CTO JSON document."""

    document: dict[str, Any]
    content_profile: dict[str, Any]
    content: dict[str, Any]
    observations: dict[str, list[dict[str, Any]]]
    historical_identity: dict[str, Any]
    historical_metadata: dict[str, Any]


def cto_json_document(
    cto: CTO,
    *,
    session_code: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Serialize a CTO into the canonical document family used for import/export."""
    document_metadata = dict(metadata or {})
    if session_code is not None:
        document_metadata["session_code"] = session_code
    return {
        "schema": CTO_JSON_SCHEMA,
        "version": CTO_JSON_VERSION,
        "cto": cto.to_dict(),
        "metadata": document_metadata,
    }


def load_cto_json_document(path: str | Path) -> dict[str, Any]:
    """Load a canonical CTO JSON document from disk."""
    file_path = Path(path).expanduser()
    with file_path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("cto_json document must be a JSON object")
    return data


def normalize_cto_json_document(document: Mapping[str, Any]) -> NormalizedImportedCTO:
    """Validate and normalize a canonical CTO JSON document for import."""
    schema = document.get("schema")
    version = document.get("version")
    if schema != CTO_JSON_SCHEMA:
        raise ValueError(
            f"cto_json document schema must be {CTO_JSON_SCHEMA!r}; got {schema!r}"
        )
    if version != CTO_JSON_VERSION:
        raise ValueError(
            f"cto_json document version must be {CTO_JSON_VERSION!r}; got {version!r}"
        )

    cto_dict = document.get("cto")
    if not isinstance(cto_dict, Mapping):
        raise ValueError("cto_json document requires object field 'cto'")

    content_profile = cto_dict.get("content_profile")
    if not isinstance(content_profile, Mapping):
        raise ValueError(
            "cto_json document requires object field 'cto.content_profile'"
        )
    profile_id = content_profile.get("id")
    profile_version = content_profile.get("version")
    if not isinstance(profile_id, str) or not profile_id:
        raise ValueError(
            "cto_json document requires non-empty 'cto.content_profile.id'"
        )
    if not isinstance(profile_version, int):
        raise ValueError("cto_json document requires int 'cto.content_profile.version'")

    content = cto_dict.get("content")
    if not isinstance(content, Mapping):
        raise ValueError("cto_json document requires object field 'cto.content'")

    observations_raw = cto_dict.get("observations", {})
    if not isinstance(observations_raw, Mapping):
        raise ValueError(
            "cto_json document field 'cto.observations' must be an object when present"
        )
    observations: dict[str, list[dict[str, Any]]] = {}
    for namespace, entries in observations_raw.items():
        if not isinstance(namespace, str) or not namespace:
            raise ValueError(
                "cto_json observations namespace keys must be non-empty str"
            )
        if not isinstance(entries, list):
            raise ValueError(
                "cto_json observations"
                f"[{namespace!r}] must be a list; got {type(entries).__name__}"
            )
        normalized_entries: list[dict[str, Any]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError(
                    f"cto_json observations[{namespace!r}] entries must be objects"
                )
            normalized_entries.append(dict(entry))
        observations[namespace] = normalized_entries

    metadata = document.get("metadata", {})
    if not isinstance(metadata, Mapping):
        raise ValueError("cto_json document field 'metadata' must be an object")

    historical_identity = {
        "turn_id": cto_dict.get("turn_id"),
        "session_id": cto_dict.get("session_id"),
        "created_at_ms": cto_dict.get("created_at_ms"),
        "last_event_id": cto_dict.get("last_event_id"),
    }
    historical_metadata = dict(metadata)

    normalized_document = {
        "schema": CTO_JSON_SCHEMA,
        "version": CTO_JSON_VERSION,
        "cto": {
            "turn_id": cto_dict.get("turn_id"),
            "session_id": cto_dict.get("session_id"),
            "created_at_ms": cto_dict.get("created_at_ms"),
            "content_profile": {"id": profile_id, "version": profile_version},
            "content": dict(content),
            "observations": observations,
            "last_event_id": cto_dict.get("last_event_id"),
        },
        "metadata": historical_metadata,
    }

    return NormalizedImportedCTO(
        document=normalized_document,
        content_profile={"id": profile_id, "version": profile_version},
        content=dict(content),
        observations=observations,
        historical_identity=historical_identity,
        historical_metadata=historical_metadata,
    )
