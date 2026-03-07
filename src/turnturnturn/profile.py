"""
Profile system — declarative schema objects for CTO content interpretation.

A Profile owns everything needed to interpret a content shape:
  - required field validation
  - optional field defaulting (with access to mutable per-session context)
  - accessor resolution (name → content value)

Profiles are registered with ProfileRegistry at startup — once, at the
class level. CTO.__getattr__ dispatches to ProfileRegistry.resolve() for
unknown attribute lookups. No profile-specific code lives in CTO or hub.

Built-in profiles live in the `profiles/` subpackage — one module per
profile. To add a new profile: create a module in `profiles/`, implement
a build() function, register it in ProfileRegistry.load_defaults(). No
changes to this module or any other core module required.

ProfileRegistry is process-scoped — all hubs in the same process share the
same registry. This is correct: profiles are declarative metadata registered
once at startup, not runtime state that varies per hub instance.

Session context:
  The hub maintains an opaque per-session context dict for each active
  session and passes it to Profile.apply_defaults() as a mutable dict.
  Profiles may read from and write to this dict freely — the hub never
  inspects its contents. This allows profiles to maintain session-scoped
  state (e.g. speaker ordinals) without leaking domain knowledge into the hub.

## FUTURE: Declarative profile system

TODO(declarative-profiles): The current implementation uses FieldSpec objects
with path tuples to describe content fields. The intended future state is a
fully declarative dict-based profile format that requires no Python code —
profiles could be loaded from JSON or YAML and written by non-programmers.

The declarative format will look like:

    Profile(
        profile_id="conversation",
        field_interpolation={
            "<level_1_key>": {"<level_2_key>": None}
        },
        content={
            "speaker": {
                "id":    {"type": "str", "field_attributes": {"required": True,  "autogenerate": False}},
                "label": {"type": "str", "field_attributes": {"required": False, "autogenerate": "<level_1_key>_<_ordinal_>"}},
                "role":  {"type": "str", "field_attributes": {"required": False, "autogenerate": "<level_1_key>"}},
            },
            "text": {"type": "str", "field_attributes": {"required": True, "autogenerate": False}},
        },
        accessor_rule={
            "name": "key_concatenation_rule",
            "rule": "<level_1_key>_<level_2_key>",
        },
        _ordinal_={"match_on": "speaker.id"},
    )

Token conventions:
  <level_1_key>   — resolves to the actual key name at depth 1
  <level_2_key>   — resolves to the actual key name at depth 2
  <_ordinal_>     — magic token; resolves to a per-session stable ordinal
                    keyed on the field path specified in _ordinal_.match_on

The migration path: Profile.from_dict(declaration) as a classmethod that
parses the declarative format and produces a Profile object identical to
what the current machinery consumes. Existing hand-constructed profiles
continue working unchanged. The seam is here — Profile.resolve(),
Profile.validate(), and Profile.apply_defaults() signatures must not change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

# ---------------------------------------------------------------------------
# Path-walking helpers
# ---------------------------------------------------------------------------


def _get_by_path(content: Any, path: tuple[str, ...]) -> Any:
    """
    Traverse a nested dict by a sequence of keys and return the value.

    Returns None if any intermediate key is absent or if a value along the
    path is not a dict. Does not raise — callers check the return value.

    Args:
        content: The root dict to traverse.
        path: Sequence of string keys describing the nested location,
            e.g. ("speaker", "id") for content["speaker"]["id"].

    Returns:
        The value at the final key, or None if the path cannot be resolved.
    """
    val: Any = content
    for key in path:
        if not isinstance(val, dict):
            return None
        val = val.get(key)
    return val


def _set_by_path(
    content: dict[str, Any],
    path: tuple[str, ...],
    value: Any,
) -> None:
    """
    Write a value into a nested dict at the location described by path.

    Creates intermediate dicts as needed. Mutates content in place.

    Args:
        content: The root dict to write into.
        path: Sequence of string keys describing the nested location.
            Must have at least one element.
        value: The value to write at the final key.
    """
    node: dict[str, Any] = content
    for key in path[:-1]:
        if key not in node or not isinstance(node[key], dict):
            node[key] = {}
        node = node[key]
    node[path[-1]] = value


def _deep_copy_content(content: dict[str, Any]) -> dict[str, Any]:
    """
    Return a copy of a content dict suitable for apply_defaults mutation.

    Copies the top-level dict and any immediately nested dicts so that
    _set_by_path writes do not mutate the caller's original content.
    Values that are not dicts are not copied — they are immutable by
    convention (str, int, etc.).

    Args:
        content: The content dict to copy.

    Returns:
        A new dict with top-level nested dicts also copied one level deep.
    """
    return {k: dict(v) if isinstance(v, dict) else v for k, v in content.items()}


# ---------------------------------------------------------------------------
# FieldSpec
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldSpec:
    """
    Declaration for a single field in a content profile.

    Combines required/optional status, type contract, and default resolution.
    The Profile uses FieldSpecs to validate content, apply defaults, and
    resolve CTO accessors — all by walking the `path` tuple into the nested
    content dict. The flat `name` (e.g. "speaker_id") is the CTO accessor
    handle only; it is never used as a content key.

    Args:
        name: The accessor name on the CTO (e.g. "speaker_id"). Derived
            by the parent_child convention from the content path.
        path: Location of this field in the nested content dict, as a
            tuple of keys (e.g. ("speaker", "id") for content["speaker"]["id"],
            ("text",) for a root-level field). This is the source of truth
            for all content traversal — validate(), apply_defaults(), and
            resolve() all walk this path.
        required: If True, must be present and correctly typed at validation.
        expected_type: Python type checked via isinstance() during validation.
        default_factory: Called with (content, session_context) to produce a
            default when the field is absent or None. May read from and write
            to session_context to maintain per-session state. None means no
            default — absent optional fields stay absent.

    TODO(declarative-profiles): FieldSpec will be replaced by the declarative
    field dict format when Profile.from_dict() is implemented. The path tuple
    is the direct equivalent of the nested key position in the declarative
    content dict. The seam is Profile.resolve(), Profile.validate(), and
    Profile.apply_defaults() — their signatures must not change.
    """

    name: str
    path: tuple[str, ...]
    required: bool = True
    expected_type: type = str
    default_factory: Callable[[dict[str, Any], dict[str, Any]], Any] | None = None


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


@dataclass
class Profile:
    """
    A self-contained schema object for one content profile.

    Owns validation, default application, and accessor resolution for a
    (profile_id, version) pair. Registered with ProfileRegistry at startup;
    consulted by ProfileRegistry.resolve() at CTO attribute access time.

    Args:
        profile_id: String identifier (e.g. "conversation").
        version: Integer version. Allows multiple versions of the same
            profile to coexist in the registry.
        fields: FieldSpec declarations keyed by accessor name.
        strict: If True, unknown keys in content are rejected at validation.
            Overridden to True when hub strict_profiles=True.

    TODO(declarative-profiles): Profile.from_dict(declaration) will be added
    as a classmethod that parses the declarative dict format (see module
    docstring) and produces a Profile object equivalent to hand-constructed
    ones. The three methods below — validate(), apply_defaults(), resolve() —
    are the stable seam. Their signatures must not change when from_dict()
    is implemented.
    """

    profile_id: str
    version: int = 1
    fields: dict[str, FieldSpec] = field(default_factory=dict)
    strict: bool = False

    def validate(self, content: Mapping[str, Any], *, strict: bool = False) -> None:
        """
        Validate that content satisfies this profile's field contract.

        Checks required fields for presence and correct type by traversing
        each FieldSpec's path tuple into the nested content dict. Optional
        fields are not checked for presence — they will be filled by
        apply_defaults().

        Args:
            content: The content dict to validate. May be arbitrarily nested;
                field locations are determined by FieldSpec.path, not by the
                flat accessor name.
            strict: If True (or self.strict is True), reject unknown top-level
                keys. Full parent_child key convention enforcement is deferred
                pending real usage driving requirements.

        Raises:
            ValueError: If a required field is missing or wrong type, or if
                strict mode finds unknown top-level keys.
        """
        effective_strict = strict or self.strict

        for name, spec in self.fields.items():
            if not spec.required:
                continue
            value = _get_by_path(content, spec.path)
            if not isinstance(value, spec.expected_type):
                path_str = ".".join(spec.path)
                raise ValueError(
                    f"{self.profile_id!r} profile requires "
                    f"content[{path_str!r}]: {spec.expected_type.__name__}"
                )

        if effective_strict:
            # v0: unknown top-level key rejection only.
            # Full convention enforcement deferred pending real usage.
            top_level_known = {spec.path[0] for spec in self.fields.values()}
            unknown = set(content.keys()) - top_level_known
            if unknown:
                raise ValueError(
                    f"{self.profile_id!r} profile (strict): "
                    f"unknown keys {sorted(unknown)}"
                )

    def apply_defaults(
        self,
        content: dict[str, Any],
        session_context: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Fill optional fields with defaults where absent or None.

        Returns a new content dict — does not mutate the caller's content.
        Traverses each FieldSpec's path tuple to locate the field in the
        nested content structure. If the value at that path is absent or not
        the expected type, the default_factory is called and the result is
        written back at the correct nested location via _set_by_path.

        May read from and write to session_context to maintain per-session
        state across calls. The hub passes the same mutable context dict for
        all turns within a session; the profile owns its contents entirely.

        Args:
            content: Validated content dict.
            session_context: Mutable per-session context dict, owned by the
                hub and passed through opaquely. Profiles use this to track
                session-scoped state (e.g. speaker ordinals for label defaults).

        Returns:
            New content dict with defaults applied at their correct nested paths.
        """
        out = _deep_copy_content(content)
        for name, spec in self.fields.items():
            if spec.required:
                continue
            value = _get_by_path(out, spec.path)
            if not isinstance(value, spec.expected_type):
                if spec.default_factory is not None:
                    _set_by_path(
                        out, spec.path, spec.default_factory(out, session_context)
                    )
        return out

    def resolve(self, name: str, content: dict[str, Any]) -> Any:
        """
        Resolve a named accessor against content by traversing FieldSpec.path.

        Called by ProfileRegistry.resolve(). Walks the path tuple into the
        nested content dict to retrieve the value. Raises KeyError for
        unknown accessor names so that CTO.__getattr__ can convert to
        AttributeError.

        Computed accessors (fields derived from multiple content keys) are
        not supported in v0. Override this method on a Profile subclass for
        computed accessor support; register the subclass with ProfileRegistry.
        No core changes required.

        Args:
            name: Attribute name to resolve (e.g. "speaker_id").
            content: The CTO's content dict (nested structure).

        Returns:
            The field value at FieldSpec.path, or None if any intermediate
            key is absent.

        Raises:
            KeyError: If name is not a registered field for this profile.
        """
        if name not in self.fields:
            raise KeyError(
                f"{self.profile_id!r} v{self.version} has no accessor {name!r}"
            )
        return _get_by_path(content, self.fields[name].path)


# ---------------------------------------------------------------------------
# ProfileRegistry — process-scoped class-level registry
# ---------------------------------------------------------------------------


class ProfileRegistry:
    """
    Process-scoped registry of Profile objects, keyed by (profile_id, version).

    Class-level state — all hubs in the same process share the same registry.
    This is correct: profiles are declarative metadata registered once at
    startup, not runtime state that varies per hub.

    TTT.register_profile() delegates here. CTO.__getattr__ calls
    ProfileRegistry.resolve() directly — no instance reference needed.

    Pre-loaded with built-in profiles via ProfileRegistry.load_defaults(),
    called automatically by TTT.create().
    """

    _profiles: dict[tuple[str, int], Profile] = {}
    _defaults_loaded: bool = False

    @classmethod
    def register(cls, profile: Profile) -> None:
        """
        Register a Profile under (profile_id, version).

        Overwrites any existing registration for the same key. Safe to call
        at any time — existing CTOs are unaffected (they carry id and version
        and will resolve against the new registration on next access).

        Args:
            profile: The Profile to register.
        """
        cls._profiles[(profile.profile_id, profile.version)] = profile

    @classmethod
    def get(cls, profile_id: str, version: int = 1) -> Profile:
        """
        Look up a Profile by (profile_id, version).

        Args:
            profile_id: The profile identifier string.
            version: Profile version. Defaults to 1.

        Returns:
            The registered Profile.

        Raises:
            KeyError: If no profile is registered for (profile_id, version).
        """
        key = (profile_id, version)
        try:
            return cls._profiles[key]
        except KeyError:
            raise KeyError(
                f"No profile registered for id={profile_id!r} version={version}"
            )

    @classmethod
    def resolve(
        cls,
        profile_id: str,
        version: int,
        name: str,
        content: dict[str, Any],
    ) -> Any:
        """
        Resolve a named accessor for a (profile_id, version) against content.

        Called by CTO.__getattr__. Looks up the Profile, delegates to
        Profile.resolve(). Raises KeyError if the profile is unknown or the
        name is not a registered accessor — CTO.__getattr__ converts to
        AttributeError.

        Args:
            profile_id: The profile identifier string.
            version: Profile version.
            name: Attribute name to resolve.
            content: The CTO's content dict.

        Returns:
            The resolved value (may be None for absent optional fields).

        Raises:
            KeyError: If profile is unknown or name is not a registered accessor.
        """
        return cls.get(profile_id, version).resolve(name, content)

    @classmethod
    def load_defaults(cls) -> None:
        """
        Register built-in profiles if not already loaded.

        Idempotent — safe to call multiple times. Called by TTT.create().
        Built-in profiles are defined in the profiles/ subpackage.
        Currently registers: conversation v1.
        """
        if cls._defaults_loaded:
            return
        from .profiles import build_conversation

        cls.register(build_conversation())
        cls._defaults_loaded = True

    @classmethod
    def __contains__(cls, key: tuple[str, int]) -> bool:
        """Return True if a profile is registered for (profile_id, version)."""
        return key in cls._profiles
