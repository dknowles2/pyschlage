"""API for interacting with the Schlage WiFi cloud service."""

from __future__ import annotations

from . import request
from .auth import Auth
from .common import send
from .lock import Lock
from .user import User


class Schlage:
    """API for interacting with the Schlage WiFi cloud service."""

    def __init__(self, auth: Auth) -> None:
        """Instantiates a Schlage API object.

        :param auth: Authentication and transport for the API.
        :type auth: pyschlage.Auth
        """
        self._auth = auth

    def locks(self, include_access_codes: bool = False) -> list[Lock]:
        """Retrieves all locks associated with this account.

        :param include_access_codes: Whether to also refresh access codes.
        :rtype: list[pyschlage.lock.Lock]
        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        response = send(self._auth, request.get_locks())
        locks = []
        for lock_json in response.json():
            lock = Lock.from_json(self._auth, lock_json)
            if include_access_codes:
                lock.refresh_access_codes()
            locks.append(lock)
        return locks

    def users(self) -> list[User]:
        """Retrieves all users associated with this account's locks.

        :rtype: list[User]
        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        response = send(self._auth, request.get_users())
        return [User.from_json(u) for u in response.json()]
