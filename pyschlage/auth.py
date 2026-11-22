"""Authentication support for the Schlage WiFi cloud service."""

from __future__ import annotations

import base64
from collections.abc import Callable
from functools import wraps
import json
import threading
import time
from typing import Any, TypeVar

from botocore.exceptions import ClientError
import pycognito
from pycognito import utils
import requests

from .exceptions import NotAuthorizedError, UnknownError

_DEFAULT_TIMEOUT = 60
_NOT_AUTHORIZED_ERRORS = (
    "NotAuthorizedException",
    "InvalidPasswordException",
    "PasswordResetRequiredException",
    "UserNotFoundException",
    "UserNotConfirmedException",
)
API_KEY = "hnuu9jbbJr7MssFDWm5nU2Z7nG5Q5rxsaqWsE7e9"
BASE_URL = "https://api.allegion.yonomi.cloud/v1"
CLIENT_ID = "t5836cptp2s1il0u9lki03j5"
CLIENT_SECRET = "1kfmt18bgaig51in4j4v1j3jbe7ioqtjhle5o6knqc5dat0tpuvo"
USER_POOL_REGION = "us-west-2"
USER_POOL_ID = USER_POOL_REGION + "_2zhrVs9d4"

_R = TypeVar("_R")
_Req = TypeVar("_Req", requests.Request, requests.PreparedRequest)


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    """Decodes the payload of a JWT without verifying its signature."""
    payload_b64 = token.split(".")[1]
    padding = "=" * (-len(payload_b64) % 4)
    return json.loads(base64.urlsafe_b64decode(payload_b64 + padding))


def _translate_auth_errors(fn: Callable[..., _R]) -> Callable[..., _R]:
    @wraps(fn)
    def wrapper(*args, **kwargs) -> _R:
        try:
            return fn(*args, **kwargs)
        except ClientError as ex:
            resp_err = ex.response.get("Error", {})
            if resp_err.get("Code") in _NOT_AUTHORIZED_ERRORS:
                raise NotAuthorizedError(
                    resp_err.get("Message", "Not authorized")
                ) from ex
            raise UnknownError(str(ex)) from ex

    return wrapper


def _translate_http_errors(
    fn: Callable[..., requests.Response],
) -> Callable[..., requests.Response]:
    @wraps(fn)
    def wrapper(*args, **kwargs) -> requests.Response:
        resp = fn(*args, **kwargs)
        try:
            resp.raise_for_status()
            return resp
        except requests.HTTPError as ex:
            try:
                message = resp.json().get("message", resp.reason)
            except requests.JSONDecodeError:
                message = resp.reason
            raise UnknownError(message) from ex

    return wrapper


class _Cognito(pycognito.Cognito):
    """pycognito.Cognito subclass with a timezone-safe check_token().

    ``pycognito.Cognito.check_token()`` compares naive local datetimes
    (``datetime.now()`` vs ``datetime.fromtimestamp(exp)``), which treats
    newly issued tokens as immediately expired during a DST fall-back hour
    because Python ignores ``fold`` when comparing naive datetimes.
    """

    def check_token(self, renew: bool = True) -> bool:
        """Checks the ``exp`` claim of the access token using UTC time."""
        if not self.access_token:
            raise AttributeError("Access Token Required to Check Token")
        dec_access_token = _decode_jwt_payload(self.access_token)
        expired: bool = time.time() >= dec_access_token["exp"]
        if expired and renew:
            self.renew_access_token()
        return expired


class _ThreadSafeRequestsSrpAuth(utils.RequestsSrpAuth):
    """RequestsSrpAuth subclass that serializes token authentication and renewal."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._lock = threading.Lock()

    def __call__(self, request: _Req) -> _Req:
        with self._lock:
            return super().__call__(request)


class Auth:
    """Handles authentication for the Schlage WiFi cloud service."""

    def __init__(self, username: str, password: str) -> None:
        """Initializes an Auth object.

        :param username: The username associated with the Schlage account.
        :type username: str
        :param password: The password for the account.
        :type password: str
        """
        self.cognito = _Cognito(
            username=username,
            user_pool_region=USER_POOL_REGION,
            user_pool_id=USER_POOL_ID,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
        )
        self.auth = _ThreadSafeRequestsSrpAuth(
            password=password,
            cognito=self.cognito,
        )
        self._user_id: str | None = None
        self._user_id_lock = threading.Lock()

    @_translate_auth_errors
    def authenticate(self):
        """Performs authentication with AWS.

        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        self.auth(requests.Request())

    @property
    def user_id(self) -> str:
        """Returns the unique user id for the authenticated user."""
        with self._user_id_lock:
            if self._user_id is None:
                self._user_id = self._get_user_id()
            return self._user_id

    def _get_user_id(self) -> str:
        resp = self.request("get", "users/@me")
        return resp.json()["identityId"]

    @_translate_http_errors
    @_translate_auth_errors
    def request(
        self, method: str, path: str, base_url: str = BASE_URL, **kwargs
    ) -> requests.Response:
        """Performs a request against the Schlage WiFi cloud service.

        :meta private:
        """
        kwargs["auth"] = self.auth
        if "headers" not in kwargs:
            kwargs["headers"] = {}
        kwargs["headers"]["X-Api-Key"] = API_KEY
        kwargs.setdefault("timeout", _DEFAULT_TIMEOUT)
        # pylint: disable=missing-timeout
        return requests.request(method, f"{base_url}/{path.lstrip('/')}", **kwargs)
