"""Tests for CTO and CTOIndex (cto.py).

Coverage areas:
  - CTO is frozen (immutable)
  - Profile accessor dispatch via __getattr__ → ProfileRegistry
  - Unknown accessor raises AttributeError
  - to_dict() serialisation
  - to_index() produces correct CTOIndex
  - CTOIndex.to_dict() serialisation
  - Observations default to empty dict
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from turnturnturn import CTO, TTT, InMemoryPersistencePurpose
from turnturnturn.cto import CTOIndex

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_cto(**kwargs) -> CTO:
    """Return a minimal CTO with conversation profile."""
    defaults = dict(
        turn_id=uuid4(),
        session_id=uuid4(),
        started_at_ms=1_000_000,
        content_profile={"id": "conversation", "version": 1},
        content={
            "speaker": {"id": "usr_x", "role": "user", "label": "Alice"},
            "text": "hello",
        },
    )
    defaults.update(kwargs)
    return CTO(**defaults)


# Ensure conversation profile is loaded for accessor tests
TTT.start(InMemoryPersistencePurpose())


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


def test_cto_is_frozen():
    cto = _make_cto()
    with pytest.raises((AttributeError, TypeError)):
        cto.turn_id = uuid4()  # type: ignore[misc]


def test_cto_observations_default_empty():
    cto = _make_cto()
    assert cto.observations == {}


# ---------------------------------------------------------------------------
# Profile accessor dispatch
# ---------------------------------------------------------------------------


def test_cto_speaker_id_accessor():
    cto = _make_cto()
    assert cto.speaker_id == "usr_x"


def test_cto_speaker_role_accessor():
    cto = _make_cto()
    assert cto.speaker_role == "user"


def test_cto_speaker_label_accessor():
    cto = _make_cto()
    assert cto.speaker_label == "Alice"


def test_cto_text_accessor():
    cto = _make_cto()
    assert cto.text == "hello"


def test_cto_unknown_accessor_raises_attribute_error():
    cto = _make_cto()
    with pytest.raises(AttributeError):
        _ = cto.nonexistent_field


def test_cto_unknown_profile_accessor_raises_attribute_error():
    """A known accessor name on an unregistered profile must raise AttributeError."""
    cto = CTO(
        turn_id=uuid4(),
        session_id=uuid4(),
        started_at_ms=0,
        content_profile={"id": "unregistered_profile", "version": 1},
        content={"x": "y"},
    )
    with pytest.raises(AttributeError):
        _ = cto.speaker_id


# ---------------------------------------------------------------------------
# to_dict()
# ---------------------------------------------------------------------------


def test_cto_to_dict_contains_expected_keys():
    cto = _make_cto()
    d = cto.to_dict()
    assert set(d.keys()) == {
        "turn_id",
        "session_id",
        "started_at_ms",
        "content_profile",
        "content",
        "observations",
        "last_event_id",
    }


def test_cto_to_dict_uuids_are_strings():
    cto = _make_cto()
    d = cto.to_dict()
    assert isinstance(d["turn_id"], str)
    assert isinstance(d["session_id"], str)
    # Verify they round-trip to UUID
    UUID(d["turn_id"])
    UUID(d["session_id"])


def test_cto_to_dict_content_profile_is_plain_dict():
    cto = _make_cto()
    d = cto.to_dict()
    assert d["content_profile"] == {"id": "conversation", "version": 1}


def test_cto_to_dict_observations_included():
    obs = {"annotator": [{"key": "tag", "value": "important"}]}
    cto = _make_cto(observations=obs)
    d = cto.to_dict()
    assert d["observations"] == obs


# ---------------------------------------------------------------------------
# to_index()
# ---------------------------------------------------------------------------


def test_cto_to_index_returns_cto_index():
    cto = _make_cto()
    assert isinstance(cto.to_index(), CTOIndex)


def test_cto_to_index_carries_correct_fields():
    cto = _make_cto()
    idx = cto.to_index()
    assert idx.turn_id == cto.turn_id
    assert idx.session_id == cto.session_id
    assert idx.content_profile == cto.content_profile
    assert idx.started_at_ms == cto.started_at_ms


def test_cto_to_index_does_not_carry_content_or_observations():
    cto = _make_cto(observations={"p": [{"key": "x", "value": 1}]})
    idx = cto.to_index()
    assert not hasattr(idx, "content")
    assert not hasattr(idx, "observations")


# ---------------------------------------------------------------------------
# CTOIndex
# ---------------------------------------------------------------------------


def test_cto_index_is_frozen():
    idx = CTOIndex(
        turn_id=uuid4(),
        session_id=uuid4(),
        content_profile={"id": "conversation", "version": 1},
        started_at_ms=0,
    )
    with pytest.raises((AttributeError, TypeError)):
        idx.turn_id = uuid4()  # type: ignore[misc]


def test_cto_index_to_dict_uuids_are_strings():
    cto = _make_cto()
    d = cto.to_index().to_dict()
    assert isinstance(d["turn_id"], str)
    assert isinstance(d["session_id"], str)
    UUID(d["turn_id"])
    UUID(d["session_id"])


def test_cto_index_to_dict_keys():
    idx = _make_cto().to_index()
    d = idx.to_dict()
    assert set(d.keys()) == {
        "turn_id",
        "session_id",
        "content_profile",
        "started_at_ms",
        "last_event_id",
    }
