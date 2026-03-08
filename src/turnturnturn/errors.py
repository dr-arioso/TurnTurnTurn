"""
TTT exception hierarchy.

All TTT-specific exceptions inherit from TTTError so consuming projects can
catch the broad case or specific subtypes as needed.
"""


class TTTError(Exception):
    """Base class for all TTT exceptions."""


class UnauthorizedDispatchError(TTTError):
    """
    Raised when a Purpose-originated event fails hub ingress authentication
    or when a hub-authored event is delivered to a Purpose with invalid
    routing credentials.

    At hub ingress, this means the submitted event's claimed sender does not
    match the registration resolved from hub_token.

    At Purpose downlink, this means take_turn() was called from outside the
    registering hub — either directly by another Purpose or by code that
    fabricated a hub-looking event without going through hub dispatch.
    """


class InvalidDownlinkSignatureError(TTTError):
    """
    Raised when a Purpose rejects a hub-authored event whose
    downlink_signature does not match the signature assigned at registration.

    This is an anti-bypass / route-integrity check. It is intended to catch
    accidental or local architectural violations, not to provide adversarial
    cryptographic security guarantees.
    """


class UnknownEventTypeError(TTTError):
    """
    Raised when hub.take_turn() receives an event_type that has no routing
    rule in the hub ingress table.
    """


class UnboundPurposeError(TTTError):
    """
    Raised when a Purpose that has not been registered with a hub attempts
    to receive a hub-authored event via take_turn().

    A Purpose is unbound if its hub token and downlink signature have not yet
    been assigned by a hub. Register the Purpose with ttt.start_purpose()
    before use.
    """


class PersistenceFailureError(TTTError):
    """
    Raised when the persistence Purpose's write_event() fails during multicast.

    The hub treats persistence failure as fatal for the affected event — no
    domain Purposes receive the event if the persistence write does not
    complete successfully. This enforces the invariant that every event
    reaches a durable sink before any other routing.

    Attributes:
        persister_name: The name of the persistence Purpose that failed.
        event_id: The event_id of the event that could not be persisted.
    """

    def __init__(self, message: str, *, persister_name: str, event_id: object) -> None:
        """Initialise with a message and structured failure context."""
        super().__init__(message)
        self.persister_name = persister_name
        self.event_id = event_id
