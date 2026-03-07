"""Tests for the TTT exception hierarchy (errors.py).

Coverage areas:
  - All exceptions are subclasses of TTTError
  - Exceptions can be raised and caught by their specific type
  - Exceptions can be caught by the base TTTError type
"""

from __future__ import annotations

import pytest

from turnturnturn.errors import TTTError, UnauthorizedDispatchError, UnboundPurposeError


def test_ttt_error_is_exception():
    assert issubclass(TTTError, Exception)


def test_unauthorized_dispatch_error_is_ttt_error():
    assert issubclass(UnauthorizedDispatchError, TTTError)


def test_unbound_purpose_error_is_ttt_error():
    assert issubclass(UnboundPurposeError, TTTError)


def test_catch_unauthorized_by_base():
    with pytest.raises(TTTError):
        raise UnauthorizedDispatchError("mismatch")


def test_catch_unbound_by_base():
    with pytest.raises(TTTError):
        raise UnboundPurposeError("not registered")


def test_unauthorized_dispatch_error_message():
    err = UnauthorizedDispatchError("token mismatch detail")
    assert "token mismatch detail" in str(err)


def test_unbound_purpose_error_message():
    err = UnboundPurposeError("register first")
    assert "register first" in str(err)
