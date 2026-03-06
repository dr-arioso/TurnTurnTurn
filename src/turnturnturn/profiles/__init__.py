"""
Built-in content profiles for TurnTurnTurn.

Each profile is defined in its own module. Profiles are registered with
ProfileRegistry via ProfileRegistry.load_defaults(), called automatically
by TTT.create().

Built-in profiles:
  - conversation (v1) — human/AI interaction turns with speaker identity
    and role semantics. See profiles/conversation.py for full documentation.

To add a new built-in profile: create a module here, implement a build
function, and register it in load_defaults() in profile.py.
"""

from .conversation import build as build_conversation

__all__ = ["build_conversation"]
