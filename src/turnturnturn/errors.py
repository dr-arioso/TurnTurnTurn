"""
TTT exception hierarchy.

All TTT-specific exceptions inherit from TTTError so consuming projects can
catch the broad case or specific subtypes as needed.
"""


class TTTError(Exception):
    """Base class for all TTT exceptions."""


class UnauthorizedDispatchError(TTTError):
    """
    Raised when a HubEvent is delivered to a Purpose with an invalid or
    mismatched hub token.

    This indicates that take_turn() was called from outside the hub —
    either directly by another Purpose (point-to-point bypass) or by code
    that constructed a HubEvent without going through start_turn(). Both
    cases violate the hub-authoritative dispatch invariant.

    The hub assigns a token to each Purpose at registration time. Valid
    dispatch always originates from the hub, which embeds the matching
    token in every HubEvent it emits. Purposes never call take_turn() on
    each other directly.
    """


class UnboundPurposeError(TTTError):
    """
    Raised when a Purpose that has not been registered with a hub attempts
    to receive a HubEvent via take_turn().

    A Purpose is unbound if its token has not yet been assigned by a hub.
    Register the Purpose with ttt.start_purpose() before use.
    """
