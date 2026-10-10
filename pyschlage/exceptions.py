"""Exceptions used in pyschlage."""


class Error(Exception):
    """Base error class."""


class NotAuthenticatedError(Error):
    """Raised when a request is made to an unauthenticated object."""


class NotAuthorizedError(Error):
    """Raised when invalid credentials are used."""


class UnknownError(Error):
    """Raised when an unknown problem occurs."""


class BleSessionError(Error):
    """Raised when a Bluetooth LE session cannot be established or verified."""


class UWeaveError(Error):
    """Raised when a lock reports a failure over Bluetooth LE."""

    def __init__(self, message: str, code: int | None = None) -> None:
        """Initializes a UWeaveError.

        :param message: A human readable description of the failure.
        :type message: str
        :param code: The uWeave error code the lock reported, where it
            reported one.
        :type code: int or None
        """
        super().__init__(message)
        self.code = code
        """The uWeave error code the lock reported, or None."""
