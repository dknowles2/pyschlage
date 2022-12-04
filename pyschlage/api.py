"""API for interacting with the Schlage WiFi cloud service."""

from __future__ import annotations

from .auth import Auth
from .device import Device


class Schlage:
    """API for interacting with the Schlage WiFi cloud service."""

    def __init__(self, auth: Auth) -> None:
        """Initializer."""
        self._auth = auth

    def devices(self) -> list[Device]:
        """Retreives all devies associated with this account."""
        response = self._auth.request("get", "")
        return [Device.from_json(self._auth, d) for d in response.json()]
