"""Exceptions used in pyschlage."""


class Error(Exception):
    """Base error class."""


class NotAuthenticatedError(Error):
    """Raised when a request is made to an unauthenticated object."""


class NotAuthorizedError(Error):
    """Raised when invalid credentials are used."""


class UnknownError(Error):
    """Raised when an unknown problem occurs."""
