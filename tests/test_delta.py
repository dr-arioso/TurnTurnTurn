"""Tests for Delta (delta.py).

Coverage areas:
  - Delta construction and field access
  - Delta is frozen (immutable)
  - to_dict() serialisation — UUID fields are strings, patch passes through
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from turnturnturn import Delta


def _make_delta(**kwargs) -> Delta:
    defaults = dict(
        delta_id=uuid4(),
        session_id=uuid4(),
        turn_id=uuid4(),
        purpose_name="test_purpose",
        purpose_id=uuid4(),
        patch={"observations": ["item_1"]},
    )
    defaults.update(kwargs)
    return Delta(**defaults)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_delta_fields_accessible():
    pid = uuid4()
    d = _make_delta(purpose_name="annotator", purpose_id=pid)
    assert d.purpose_name == "annotator"
    assert d.purpose_id == pid


def test_delta_is_frozen():
    d = _make_delta()
    with pytest.raises((AttributeError, TypeError)):
        d.purpose_name = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# to_dict()
# ---------------------------------------------------------------------------


def test_to_dict_keys():
    d = _make_delta()
    result = d.to_dict()
    assert set(result.keys()) == {
        "delta_id",
        "session_id",
        "turn_id",
        "purpose_name",
        "purpose_id",
        "patch",
    }


def test_to_dict_uuid_fields_are_strings():
    d = _make_delta()
    result = d.to_dict()
    for key in ("delta_id", "session_id", "turn_id", "purpose_id"):
        assert isinstance(result[key], str), f"{key} should be a string"
        UUID(result[key])  # must be valid UUID


def test_to_dict_purpose_name_is_string():
    d = _make_delta(purpose_name="my_purpose")
    assert d.to_dict()["purpose_name"] == "my_purpose"


def test_to_dict_patch_passes_through():
    patch = {"tags": ["a", "b"], "score": [0.9]}
    d = _make_delta(patch=patch)
    assert d.to_dict()["patch"] == patch


def test_to_dict_empty_patch():
    d = _make_delta(patch={})
    assert d.to_dict()["patch"] == {}
