"""Authentication support for the Schlage WiFi cloud service."""

from __future__ import annotations

import pycognito
from pycognito import utils
import requests

_DEFAULT_TIMEOUT = 60
API_KEY = "hnuu9jbbJr7MssFDWm5nU2Z7nG5Q5rxsaqWsE7e9"
BASE_URL = "https://api.allegion.yonomi.cloud/v1/devices"
CLIENT_ID = "t5836cptp2s1il0u9lki03j5"
CLIENT_SECRET = "1kfmt18bgaig51in4j4v1j3jbe7ioqtjhle5o6knqc5dat0tpuvo"
USER_POOL_REGION = "us-west-2"
USER_POOL_ID = USER_POOL_REGION + "_2zhrVs9d4"


class Auth:
    """Handles authentication for the Schlage WiFi cloud service."""

    def __init__(self, username: str, password: str) -> None:
        """Initializer."""
        self._auth = utils.RequestsSrpAuth(
            password=password,
            cognito=pycognito.Cognito(
                username=username,
                user_pool_region=USER_POOL_REGION,
                user_pool_id=USER_POOL_ID,
                client_id=CLIENT_ID,
                client_secret=CLIENT_SECRET,
            ),
        )

    def authenticate(self):
        """Performs authentication with AWS."""
        self._auth()

    def request(self, method: str, path: str, **kwargs) -> requests.Response:
        """Performs a request against the Schlage WiFi cloud service."""
        kwargs["auth"] = self._auth
        if "headers" not in kwargs:
            kwargs["headers"] = {}
        kwargs["headers"]["X-Api-Key"] = API_KEY
        timeout = kwargs.pop("timeout", _DEFAULT_TIMEOUT)
        return requests.request(
            method, f"{BASE_URL}/{path.lstrip('/')}", timeout=timeout, **kwargs
        )
