"""HTTP transport for the Schlage WiFi cloud service."""

from __future__ import annotations

from typing import Any, Protocol

import aiohttp

from .auth import API_KEY, BASE_URL, Auth
from .exceptions import NotAuthorizedError, UnknownError

_DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=60)


def _stringify(params: dict[str, Any]) -> dict[str, str]:
    """Coerces query parameter values to the strings aiohttp requires."""
    return {k: str(v) for k, v in params.items()}


class Transport(Protocol):
    """The seam between the API client and the network.

    Implement this to stub out HTTP entirely in tests.
    """

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        """Performs a request and returns the decoded JSON response."""
        ...  # pragma: no cover


class AiohttpTransport:
    """A :class:`Transport` backed by an aiohttp session."""

    def __init__(
        self,
        auth: Auth,
        session: aiohttp.ClientSession,
        base_url: str = BASE_URL,
    ) -> None:
        """Initializes an AiohttpTransport.

        :param auth: Credentials for the Schlage cloud service.
        :type auth: pyschlage.Auth
        :param session: The aiohttp session to issue requests on.
        :type session: aiohttp.ClientSession
        :param base_url: The API root to issue requests against.
        :type base_url: str
        """
        self._auth = auth
        self._session = session
        self._base_url = base_url

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        """Performs a request against the Schlage WiFi cloud service.

        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        token = await self._auth.async_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Api-Key": API_KEY,
        }
        url = f"{self._base_url}/{path.lstrip('/')}"
        async with self._session.request(
            method,
            url,
            params=_stringify(params) if params else None,
            json=json,
            headers=headers,
            timeout=_DEFAULT_TIMEOUT,
        ) as resp:
            # The service is inconsistent about Content-Type, so decode
            # leniently rather than trusting the header.
            body = await resp.json(content_type=None)
            if resp.ok:
                return body
            message = resp.reason or ""
            if isinstance(body, dict):
                message = body.get("message", message)
            if resp.status in (401, 403):
                raise NotAuthorizedError(message)
            raise UnknownError(message)
