"""Authentication support for the Schlage WiFi cloud service."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import wraps
import json
from typing import TypeVar

from botocore.exceptions import ClientError
import pycognito

from .exceptions import NotAuthorizedError, UnknownError

API_KEY = "hnuu9jbbJr7MssFDWm5nU2Z7nG5Q5rxsaqWsE7e9"
BASE_URL = "https://api.allegion.yonomi.cloud/v1"
CLIENT_ID = "t5836cptp2s1il0u9lki03j5"
CLIENT_SECRET = "1kfmt18bgaig51in4j4v1j3jbe7ioqtjhle5o6knqc5dat0tpuvo"
USER_POOL_REGION = "us-west-2"
USER_POOL_ID = USER_POOL_REGION + "_2zhrVs9d4"

_NOT_AUTHORIZED_ERRORS = (
    "NotAuthorizedException",
    "InvalidPasswordException",
    "PasswordResetRequiredException",
    "UserNotFoundException",
    "UserNotConfirmedException",
)

# Renew the access token this long before it actually expires, so that a token
# does not lapse in between the expiry check and the request that uses it.
_EXPIRY_SKEW = timedelta(seconds=60)

_R = TypeVar("_R")


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


def _token_expires_at(token: str) -> datetime:
    """Returns the expiry time of a JWT without verifying its signature."""
    payload = token.split(".")[1]
    padding = "=" * (-len(payload) % 4)
    claims = json.loads(base64.urlsafe_b64decode(payload + padding))
    return datetime.fromtimestamp(claims["exp"], tz=UTC)


class Auth:
    """Manages Cognito credentials for the Schlage WiFi cloud service.

    The underlying Cognito library is synchronous and boto3-based, so token
    acquisition and renewal are dispatched to a worker thread. This is only
    paid when a token is actually minted (roughly once an hour); the common
    path checks the cached token's expiry locally and does no I/O at all.
    """

    def __init__(self, username: str, password: str) -> None:
        """Initializes an Auth object.

        :param username: The username associated with the Schlage account.
        :type username: str
        :param password: The password for the account.
        :type password: str
        """
        self._cognito = pycognito.Cognito(
            username=username,
            user_pool_region=USER_POOL_REGION,
            user_pool_id=USER_POOL_ID,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
        )
        self._password = password
        self._mu = asyncio.Lock()

    async def async_access_token(self) -> str:
        """Returns a valid access token, minting a new one if needed.

        :rtype: str
        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        if not self._needs_token():
            return self._cognito.access_token

        async with self._mu:
            # Another task may have renewed while we waited for the lock.
            if self._needs_token():
                await asyncio.to_thread(self._blocking_get_token)
        return self._cognito.access_token

    def _needs_token(self) -> bool:
        token = self._cognito.access_token
        if not token:
            return True
        return datetime.now(UTC) + _EXPIRY_SKEW >= _token_expires_at(token)

    @_translate_auth_errors
    def _blocking_get_token(self) -> None:
        """Authenticates or renews. Must be called from a worker thread."""
        if self._cognito.access_token:
            try:
                self._cognito.renew_access_token()
                return
            except ClientError:
                # The refresh token has expired or been revoked. Fall through
                # to a full re-authentication.
                pass
        self._cognito.authenticate(password=self._password)
