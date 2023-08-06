"""API for interacting with the Schlage WiFi cloud service."""

from __future__ import annotations

from .auth import Auth
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

    def locks(self) -> list[Lock]:
        """Retrieves all locks associated with this account.

        :rtype: list[Lock]
        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        path = Lock.request_path()
        response = self._auth.request("get", path, params={"archetype": "lock"})
        locks = []
        for lock_json in response.json():
            lock = Lock.from_json(self._auth, lock_json)
            lock.refresh_access_codes()
            locks.append(lock)
        return locks

    def users(self) -> list[User]:
        """Retrieves all users associated with this account's locks.

        :rtype: list[User]
        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        path = User.request_path()
        response = self._auth.request("get", path)
        return [User.from_json(u) for u in response.json()]
