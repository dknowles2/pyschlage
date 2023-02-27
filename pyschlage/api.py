"""API for interacting with the Schlage WiFi cloud service."""

from __future__ import annotations

from .auth import Auth
from .lock import Lock


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
        return [Lock.from_json(self._auth, d) for d in response.json()]
