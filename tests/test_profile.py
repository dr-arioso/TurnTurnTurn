"""Tests for the profile system (profile.py and profiles/conversation.py).

Coverage areas:
  - Path-walking helpers (_get_by_path, _set_by_path, _deep_copy_content)
  - FieldSpec construction
  - Profile.validate() — required fields, strict mode, type checking
  - Profile.apply_defaults() — fills optionals, does not mutate input
  - Profile.resolve() — happy path, unknown name raises KeyError
  - ProfileRegistry.register() / get() / resolve() / load_defaults()
  - Conversation profile: field declarations, ordinal label logic
"""

from __future__ import annotations

import pytest

from turnturnturn.profile import (
    FieldSpec,
    Profile,
    ProfileRegistry,
    _deep_copy_content,
    _get_by_path,
    _set_by_path,
)
from turnturnturn.profiles import build_conversation

# ---------------------------------------------------------------------------
# _get_by_path
# ---------------------------------------------------------------------------


def test_get_by_path_single_key():
    assert _get_by_path({"a": 1}, ("a",)) == 1


def test_get_by_path_nested():
    assert _get_by_path({"a": {"b": "found"}}, ("a", "b")) == "found"


def test_get_by_path_missing_key_returns_none():
    assert _get_by_path({"a": 1}, ("b",)) is None


def test_get_by_path_missing_intermediate_returns_none():
    assert _get_by_path({"a": {}}, ("a", "b")) is None


def test_get_by_path_non_dict_intermediate_returns_none():
    assert _get_by_path({"a": "not_a_dict"}, ("a", "b")) is None


# ---------------------------------------------------------------------------
# _set_by_path
# ---------------------------------------------------------------------------


def test_set_by_path_single_key():
    d: dict = {}
    _set_by_path(d, ("x",), 42)
    assert d["x"] == 42


def test_set_by_path_nested_creates_intermediates():
    d: dict = {}
    _set_by_path(d, ("a", "b"), "value")
    assert d == {"a": {"b": "value"}}


def test_set_by_path_overwrites_existing():
    d = {"a": {"b": "old"}}
    _set_by_path(d, ("a", "b"), "new")
    assert d["a"]["b"] == "new"


def test_set_by_path_mutates_in_place():
    d: dict = {"a": {}}
    original = d
    _set_by_path(d, ("a", "x"), 1)
    assert d is original


# ---------------------------------------------------------------------------
# _deep_copy_content
# ---------------------------------------------------------------------------


def test_deep_copy_content_does_not_mutate_original():
    original = {"speaker": {"id": "usr_x"}, "text": "hi"}
    copy = _deep_copy_content(original)
    copy["speaker"]["id"] = "mutated"
    assert original["speaker"]["id"] == "usr_x"


def test_deep_copy_content_returns_new_dict():
    d = {"a": {"b": 1}}
    assert _deep_copy_content(d) is not d


def test_deep_copy_content_non_dict_values_shared():
    """String values are immutable; no deep copy needed — they can be shared."""
    d = {"text": "hello"}
    copy = _deep_copy_content(d)
    assert copy["text"] == "hello"


# ---------------------------------------------------------------------------
# FieldSpec
# ---------------------------------------------------------------------------


def test_fieldspec_construction():
    spec = FieldSpec(
        name="speaker_id", path=("speaker", "id"), required=True, expected_type=str
    )
    assert spec.name == "speaker_id"
    assert spec.path == ("speaker", "id")
    assert spec.required is True
    assert spec.expected_type is str


def test_fieldspec_is_frozen():
    spec = FieldSpec(name="x", path=("x",))
    with pytest.raises((AttributeError, TypeError)):
        spec.name = "y"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Profile.validate()
# ---------------------------------------------------------------------------


@pytest.fixture
def simple_profile() -> Profile:
    """A minimal Profile with one required and one optional field."""
    return Profile(
        profile_id="test",
        version=1,
        fields={
            "req": FieldSpec(
                name="req", path=("required_field",), required=True, expected_type=str
            ),
            "opt": FieldSpec(
                name="opt", path=("optional_field",), required=False, expected_type=str
            ),
        },
    )


def test_validate_passes_with_required_fields(simple_profile):
    simple_profile.validate({"required_field": "present"})  # no exception


def test_validate_raises_when_required_field_missing(simple_profile):
    with pytest.raises(ValueError, match="required_field"):
        simple_profile.validate({})


def test_validate_raises_on_wrong_type(simple_profile):
    with pytest.raises(ValueError):
        simple_profile.validate({"required_field": 123})  # expects str


def test_validate_passes_when_optional_absent(simple_profile):
    simple_profile.validate({"required_field": "ok"})  # no exception


def test_validate_strict_rejects_unknown_keys(simple_profile):
    with pytest.raises(ValueError, match="unknown keys"):
        simple_profile.validate(
            {"required_field": "ok", "surprise": "not_declared"},
            strict=True,
        )


def test_validate_strict_accepts_known_keys(simple_profile):
    simple_profile.validate({"required_field": "ok"}, strict=True)  # no exception


def test_validate_profile_strict_flag_enforced(simple_profile):
    simple_profile.strict = True
    with pytest.raises(ValueError, match="unknown keys"):
        simple_profile.validate({"required_field": "ok", "extra": "bad"})


# ---------------------------------------------------------------------------
# Profile.apply_defaults()
# ---------------------------------------------------------------------------


def test_apply_defaults_does_not_mutate_input():
    profile = Profile(
        profile_id="test",
        version=1,
        fields={
            "opt": FieldSpec(
                name="opt",
                path=("opt_field",),
                required=False,
                expected_type=str,
                default_factory=lambda content, ctx: "default_val",
            ),
        },
    )
    original = {"opt_field": None}
    profile.apply_defaults(original, {})
    assert original["opt_field"] is None  # input unchanged


def test_apply_defaults_fills_missing_optional():
    profile = Profile(
        profile_id="test",
        version=1,
        fields={
            "opt": FieldSpec(
                name="opt",
                path=("opt_field",),
                required=False,
                expected_type=str,
                default_factory=lambda content, ctx: "filled",
            ),
        },
    )
    result = profile.apply_defaults({}, {})
    assert result.get("opt_field") == "filled"


def test_apply_defaults_does_not_overwrite_supplied_optional():
    profile = Profile(
        profile_id="test",
        version=1,
        fields={
            "opt": FieldSpec(
                name="opt",
                path=("opt_field",),
                required=False,
                expected_type=str,
                default_factory=lambda content, ctx: "would_overwrite",
            ),
        },
    )
    result = profile.apply_defaults({"opt_field": "supplied"}, {})
    assert result["opt_field"] == "supplied"


def test_apply_defaults_no_factory_leaves_field_absent():
    profile = Profile(
        profile_id="test",
        version=1,
        fields={
            "opt": FieldSpec(
                name="opt",
                path=("opt_field",),
                required=False,
                expected_type=str,
                default_factory=None,
            ),
        },
    )
    result = profile.apply_defaults({}, {})
    assert "opt_field" not in result


def test_apply_defaults_factory_receives_session_context():
    """The default_factory must receive the mutable session_context dict."""
    captured = {}

    def factory(content, ctx):
        captured["ctx"] = ctx
        return "x"

    profile = Profile(
        profile_id="test",
        version=1,
        fields={
            "opt": FieldSpec(
                name="opt",
                path=("f",),
                required=False,
                expected_type=str,
                default_factory=factory,
            ),
        },
    )
    ctx = {"existing": True}
    profile.apply_defaults({}, ctx)
    assert captured["ctx"] is ctx


# ---------------------------------------------------------------------------
# Profile.resolve()
# ---------------------------------------------------------------------------


def test_resolve_returns_field_value():
    profile = Profile(
        profile_id="test",
        version=1,
        fields={
            "speaker_id": FieldSpec(name="speaker_id", path=("speaker", "id")),
        },
    )
    assert profile.resolve("speaker_id", {"speaker": {"id": "usr_1"}}) == "usr_1"


def test_resolve_unknown_name_raises_key_error():
    profile = Profile(profile_id="test", version=1, fields={})
    with pytest.raises(KeyError):
        profile.resolve("does_not_exist", {})


def test_resolve_absent_optional_returns_none():
    profile = Profile(
        profile_id="test",
        version=1,
        fields={
            "opt": FieldSpec(
                name="opt", path=("opt_field",), required=False, expected_type=str
            ),
        },
    )
    assert profile.resolve("opt", {}) is None


# ---------------------------------------------------------------------------
# ProfileRegistry
# ---------------------------------------------------------------------------


def test_registry_register_and_get():
    profile = Profile(
        profile_id="reg_test_{}".format(id(object())), version=1, fields={}
    )
    ProfileRegistry.register(profile)
    retrieved = ProfileRegistry.get(profile.profile_id, 1)
    assert retrieved is profile


def test_registry_get_unknown_raises_key_error():
    with pytest.raises(KeyError):
        ProfileRegistry.get("definitely_not_registered_xyzzy", 1)


def test_registry_resolve_delegates_to_profile():
    pid = "resolve_test_{}".format(id(object()))
    profile = Profile(
        profile_id=pid,
        version=1,
        fields={
            "field_a": FieldSpec(name="field_a", path=("a",)),
        },
    )
    ProfileRegistry.register(profile)
    assert ProfileRegistry.resolve(pid, 1, "field_a", {"a": "found"}) == "found"


def test_registry_load_defaults_is_idempotent():
    """Calling load_defaults() twice must not raise."""
    ProfileRegistry.load_defaults()
    ProfileRegistry.load_defaults()  # no exception


def test_registry_contains_conversation_after_load_defaults():
    ProfileRegistry.load_defaults()
    assert ("conversation", 1) in ProfileRegistry._profiles


# ---------------------------------------------------------------------------
# Conversation profile
# ---------------------------------------------------------------------------


@pytest.fixture
def conv() -> Profile:
    return build_conversation()


def test_conversation_profile_id(conv):
    assert conv.profile_id == "conversation"
    assert conv.version == 1


def test_conversation_validate_minimal(conv):
    conv.validate({"speaker": {"id": "x"}, "text": "hello"})  # no exception


def test_conversation_validate_missing_text_raises(conv):
    with pytest.raises(ValueError):
        conv.validate({"speaker": {"id": "x"}})


def test_conversation_validate_missing_speaker_id_raises(conv):
    with pytest.raises(ValueError):
        conv.validate({"speaker": {}, "text": "hi"})


def test_conversation_apply_defaults_role(conv):
    result = conv.apply_defaults({"speaker": {"id": "x"}, "text": "hi"}, {})
    assert result["speaker"]["role"] == "speaker"


def test_conversation_apply_defaults_label_ordinal(conv):
    ctx: dict = {}
    result = conv.apply_defaults({"speaker": {"id": "alice"}, "text": "hi"}, ctx)
    assert result["speaker"]["label"] == "speaker_1"


def test_conversation_label_ordinal_increments_per_new_speaker(conv):
    ctx: dict = {}
    conv.apply_defaults({"speaker": {"id": "alice"}, "text": "t1"}, ctx)
    result = conv.apply_defaults({"speaker": {"id": "bob"}, "text": "t2"}, ctx)
    assert result["speaker"]["label"] == "speaker_2"


def test_conversation_label_ordinal_stable_for_returning_speaker(conv):
    ctx: dict = {}
    conv.apply_defaults({"speaker": {"id": "alice"}, "text": "t1"}, ctx)
    conv.apply_defaults({"speaker": {"id": "bob"}, "text": "t2"}, ctx)
    result = conv.apply_defaults({"speaker": {"id": "alice"}, "text": "t3"}, ctx)
    assert result["speaker"]["label"] == "speaker_1"


def test_conversation_explicit_label_not_overwritten(conv):
    result = conv.apply_defaults(
        {"speaker": {"id": "x", "label": "Named"}, "text": "hi"}, {}
    )
    assert result["speaker"]["label"] == "Named"


def test_conversation_resolve_speaker_id(conv):
    assert conv.resolve("speaker_id", {"speaker": {"id": "u1"}, "text": "hi"}) == "u1"


def test_conversation_resolve_text(conv):
    assert (
        conv.resolve("text", {"speaker": {"id": "u1"}, "text": "the text"})
        == "the text"
    )


def test_conversation_resolve_unknown_raises(conv):
    with pytest.raises(KeyError):
        conv.resolve("nonexistent", {})
