"""Exceptions used in pyschlage."""


class Error(Exception):
    """Base error class."""


class NotAuthenticatedError(Error):
    """Raised when a request is made to an unauthenticated object."""


class NotAuthorizedError(Error):
    """Raised when invalid credentials are used."""


class UnknownError(Error):
    """Raised when an unknown problem occurs."""


class InvalidCodeError(Error, ValueError):
    """Raised when an access code is not one the lock will accept.

    Also a :class:`ValueError`, since a non-numeric access code previously
    raised that from within a save operation.
    """
