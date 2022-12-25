"""API for interacting with the Schlage WiFi cloud service."""

from __future__ import annotations

from .auth import Auth
from .lock import Lock


class Schlage:
    """API for interacting with the Schlage WiFi cloud service."""

    def __init__(self, auth: Auth) -> None:
        """Initializer."""
        self._auth = auth

    def locks(self) -> list[Lock]:
        """Retreives all locks associated with this account."""
        path = Lock.request_path()
        response = self._auth.request("get", path, params={"archetype": "lock"})
        return [Lock.from_json(self._auth, d) for d in response.json()]
