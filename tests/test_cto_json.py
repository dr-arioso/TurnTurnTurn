"""Tests for canonical CTO JSON document helpers."""

from __future__ import annotations

from uuid import uuid4

from turnturnturn import (
    CTO,
    CTO_JSON_SCHEMA,
    CTO_JSON_VERSION,
    TTT_PROVENANCE_NAMESPACE,
    cto_json_document,
    normalize_cto_json_document,
)


def _make_cto(**kwargs) -> CTO:
    defaults = dict(
        turn_id=uuid4(),
        session_id=uuid4(),
        created_at_ms=1_000_000,
        content_profile={"id": "conversation", "version": 1},
        content={
            "speaker": {"id": "usr_x", "role": "user", "label": "Alice"},
            "text": "hello",
        },
        observations={"annotator": [{"key": "tag", "value": "important"}]},
    )
    defaults.update(kwargs)
    return CTO(**defaults)


def test_cto_json_document_wraps_cto_with_schema_and_version():
    cto = _make_cto()
    document = cto_json_document(cto, session_code="UE-01")

    assert document["schema"] == CTO_JSON_SCHEMA
    assert document["version"] == CTO_JSON_VERSION
    assert document["cto"]["turn_id"] == str(cto.turn_id)
    assert document["metadata"]["session_code"] == "UE-01"


def test_normalize_cto_json_document_preserves_live_observations_and_history():
    cto = _make_cto()
    document = cto_json_document(
        cto,
        session_code="UE-01",
        metadata={"source_note": "fixture"},
    )

    normalized = normalize_cto_json_document(document)

    assert normalized.content_profile == {"id": "conversation", "version": 1}
    assert normalized.content["text"] == "hello"
    assert normalized.observations["annotator"][0]["value"] == "important"
    assert normalized.historical_identity["turn_id"] == str(cto.turn_id)
    assert normalized.historical_metadata["session_code"] == "UE-01"
    assert normalized.historical_metadata["source_note"] == "fixture"


def test_normalize_cto_json_document_keeps_provenance_namespace_if_present():
    cto = _make_cto(
        observations={
            TTT_PROVENANCE_NAMESPACE: [
                {"key": "import", "value": {"source": {"kind": "fixture"}}}
            ]
        }
    )

    normalized = normalize_cto_json_document(cto_json_document(cto))

    assert TTT_PROVENANCE_NAMESPACE in normalized.observations
