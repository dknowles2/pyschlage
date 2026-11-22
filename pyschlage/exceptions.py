"""Exceptions used in pyschlage."""

from __future__ import annotations


class Error(Exception):
    """Base error class."""


class NotAuthenticatedError(Error):
    """Raised when a request is made to an unauthenticated object."""


class NotAuthorizedError(Error):
    """Raised when invalid credentials are used."""


class UnknownError(Error):
    """Raised when an unknown problem occurs.

    :ivar status_code: The HTTP status code returned by the service, if
        applicable.
    :vartype status_code: int | None
    """

    def __init__(self, *args: object, status_code: int | None = None) -> None:
        super().__init__(*args)
        self.status_code: int | None = status_code


class InvalidCodeError(Error, ValueError):
    """Raised when an access code is not one the lock will accept.

    Also a :class:`ValueError`, since a non-numeric access code previously
    raised that from within a save operation.
    """
