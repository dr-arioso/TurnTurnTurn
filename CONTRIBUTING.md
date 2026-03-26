# Contributing to TurnTurnTurn

This document is for humans and LLMs alike. If you are an agent working in this
repo, read `AGENTS.md` first — it covers operational context, naming history,
and things not to do. This document covers the contribution workflow.

---

## The core rule

**TTT must not accumulate domain semantics.** The `conversation` profile is an
example, not a direction. If a change makes TTT more useful for conversations
specifically at the cost of generality, it belongs in the consuming project
(e.g. Adjacency), not here.

When in doubt: would this change make sense for a researcher building an image
annotation pipeline? A document review workflow? If not, it probably doesn't
belong in TTT.

---

## Branch and PR workflow

Currently: push to `main`. This will formalize as collaborators join.

Before pushing:

```bash
pytest --cov=turnturnturn
pre-commit run --all-files
```

Both must pass cleanly. No exceptions.

---

## The docs-as-code contract

TTT uses docs-as-code: the architecture doc and API reference are maintained
alongside the code, not separately. This means doc drift is a bug, not a
backlog item.

The workflow has two layers:

**Layer 1 — Docstrings (always)**
Every public class, method, and function must have a docstring. This is
enforced by `interrogate` at commit time (threshold: 80%). The API reference
in `docs/api/` is generated from these docstrings at build time via
`mkdocstrings` — you do not edit the API reference pages directly.

**Layer 2 — Architecture doc (when the design changes)**
`docs/architecture/core_architecture.md` documents the substrate model and
layer boundaries. `docs/architecture/bootstrap_lifecycle.md` documents mesh and
session lifecycle. Update these when you change *why* something works the way
it does, not just *how*. See [When to update the arch doc](#when-to-update-the-arch-doc)
below.

---

## Docstring standards

TTT uses Google-style docstrings. `mkdocstrings` renders them; mypy checks
types. A good docstring answers three questions:

1. **What is this?** One sentence, present tense, no waffling.
2. **What does the caller need to know?** Constraints, invariants, side effects.
3. **What are the args/returns?** Only if non-obvious from the type signature.

### Good example

```python
async def start_turn(
    self,
    session_id: UUID,
    content_profile: str,
    content: dict[str, Any],
    *,
    profile_version: int = 1,
    request_id: str | None = None,
    submitted_by_label: str | None = None,
) -> UUID:
    """
    Look up the profile, validate content, apply defaults, create a CTO,
    emit cto_created, then dispatch to registered Purposes.

    The hub is the sole authority for CTO creation. Callers may not construct
    CTOs directly. If the profile is unknown or content does not satisfy the
    profile contract, an exception is raised and no CTO is created.

    Args:
        session_id: The session this turn belongs to.
        content_profile: Profile identifier string (e.g. "conversation").
            Must be registered in ProfileRegistry.
        content: Profile-conformant content dict.
        profile_version: Version of the profile to use. Defaults to 1.
        request_id: Optional caller correlation key for idempotency. Not yet
            enforced in v0.
        submitted_by_label: Optional provenance label for non-Purpose callers.

    Returns:
        The turn_id of the newly created CTO.

    Raises:
        KeyError: If content_profile / profile_version is not registered.
        ValueError: If content does not satisfy the profile contract.
    """
```

### What to avoid

```python
def start_turn(self, session_id, content_profile, content):
    """Start a turn."""  # too thin — says nothing the name doesn't already say
```

```python
def start_turn(self, session_id, content_profile, content):
    """
    This method is used to start a turn by validating the content profile
    and then creating a CTO and emitting events and dispatching purposes.
    """  # no structure, no invariants, restates the code
```

### Inline comments

Use inline comments for implementation notes that are not part of the public
contract — things a maintainer needs to know, things that will change, things
that are deliberately incomplete:

```python
# v0: naive broadcast to all registered purposes.
# Later: subscription matching by event_type + DAG eligibility gating.
```

These do not substitute for docstrings. They are not extracted into the API
reference.

---

## The interrogate threshold

The current threshold is **80%** (`pyproject.toml: [tool.interrogate]`).

If `pre-commit run --all-files` fails on `interrogate`, check coverage manually:

```bash
interrogate src/turnturnturn --verbose
```

This shows exactly which classes and methods are missing docstrings. Fix those
before committing. Do not raise the threshold to paper over a gap — add the
docstrings.

If you are adding a stub or placeholder that is intentionally undocumented for
now, add a minimal docstring that says so:

```python
def merge_delta(self, delta: Delta) -> None:
    """Merge a proposed Delta into canonical CTO state. Not yet implemented."""
    raise NotImplementedError
```

This counts toward coverage and tells the next reader (human or LLM) exactly
what the situation is.

---

## When to update the arch doc

The architecture docs are the design record. `docs/architecture/core_architecture.md`
owns the substrate model; `docs/architecture/bootstrap_lifecycle.md` owns mesh/session
lifecycle. They document *intent* and *principles*, not implementation detail.
Use this table:

| Change | Update arch doc? |
|--------|-----------------|
| New public method or class | No — docstrings + API reference handle it |
| Changed method signature | No — docstrings handle it |
| New HubEvent type | Yes — update the event taxonomy (§6) |
| New content profile | Yes — update the profiles section |
| Changed DAG or routing behavior | Yes — update §2 principles and relevant lifecycle sections |
| Renamed a core concept | Yes — update §11 migration notes with the old and new name |
| Retired a concept | Yes — add to §11, remove from core nouns (§1) |
| Bug fix | No |
| Performance change | No |

**The migration notes section (§11) is permanent history.** Do not remove
entries. If a concept was retired, future readers (and LLMs) need to know it
existed and why it's gone. This is how we avoid re-litigating settled decisions.

---

## Verifying docs locally

```bash
mkdocs serve
```

Opens at `http://127.0.0.1:8000`. The API reference pages render live from
your docstrings — if a docstring is malformed, you'll see it here before CI
does.

Before pushing any doc change:

```bash
mkdocs build --strict
```

`--strict` treats warnings as errors. This is what CI runs. If it passes
locally it will pass in CI.

---

## Adding a new content profile

No core module changes required. The profile system is designed for this.

1. Construct a `Profile` with `FieldSpec` declarations for each field, then
   register it directly on `ProfileRegistry` at process startup. Profiles are
   process-scoped and hub-independent — do not pass them through the hub:
   ```python
   from turnturnturn import Profile, FieldSpec
   from turnturnturn.profile import ProfileRegistry

   my_profile = Profile(
       profile_id="annotation",
       version=1,
       fields={
           "document_id": FieldSpec(name="document_id", required=True, expected_type=str),
           "label":       FieldSpec(name="label",       required=True, expected_type=str),
       },
   )
   ProfileRegistry.register(my_profile)
   ```
2. For optional fields with defaults, supply a `default_factory`. If the
   default depends on session-scoped state (e.g. an ordinal counter), read
   from and write to the `session_context` dict — the hub passes it through
   opaquely across all turns in a session:
   ```python
   def my_default(content, session_context):
       counter = session_context.setdefault("annotation.count", 0)
       session_context["annotation.count"] += 1
       return f"item_{counter + 1}"
   ```
3. For computed accessors (a field derived from multiple content keys),
   subclass `Profile` and override `resolve()`. Register the subclass.
4. Add a test in `tests/` covering valid content, invalid content (missing
   required fields), and default resolution.
5. Update the profiles section of the arch doc (§5).
6. Consider adding an example to `docs/index.md` if the profile is a
   canonical use case.

Do not add any profile-specific code to `cto.py`, `hub.py`, or any other
core module. If you find yourself editing a core module to support a new
profile, that is a signal the profile system needs to be extended instead.

---

## Adding a new Purpose

Purposes live in consuming projects (e.g. Adjacency), not in TTT. If you find
yourself wanting to add a Purpose to TTT itself, that is a signal that domain
semantics are leaking into the hub. Step back and ask whether the behavior
belongs in the consuming project instead.

The one exception: example or test Purposes used to demonstrate or verify TTT
behavior. These belong in `tests/` or a future `examples/` directory, clearly
marked as illustrative.

---

## Checklist

Before any push:

- [ ] `pytest --cov=turnturnturn` passes
- [ ] `pre-commit run --all-files` passes (includes interrogate, mypy --strict)
- [ ] New public surfaces have docstrings
- [ ] `mkdocs build --strict` passes if any doc files were touched
- [ ] Arch doc updated if a design decision changed (see table above)
- [ ] Migration notes updated if anything was renamed or retired
