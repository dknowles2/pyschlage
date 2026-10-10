"""The seam between the asynchronous API and the network."""

from __future__ import annotations

from typing import Any, Protocol

import aiohttp

from ..auth import API_KEY, BASE_URL, Auth
from ..exceptions import NotAuthorizedError, UnknownError
from ..request import Request

_DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=60)


def _stringify(params: dict[str, Any]) -> dict[str, str]:
    """Coerces query parameter values to the strings aiohttp requires."""
    return {k: str(v) for k, v in params.items()}


class Transport(Protocol):
    """The seam between the API client and the network.

    Implement this to stub out HTTP entirely, in tests or to reach the service
    some other way.
    """

    async def send(self, request: Request) -> Any:
        """Issues a request and returns the decoded JSON response.

        :param request: The request to issue.
        :type request: pyschlage.request.Request
        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
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

    async def send(self, request: Request) -> Any:
        """Issues a request against the Schlage WiFi cloud service.

        :param request: The request to issue.
        :type request: pyschlage.request.Request
        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        token = await self._auth.async_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Api-Key": API_KEY,
        }
        base_url = request.base_url or self._base_url
        url = f"{base_url}/{request.path.lstrip('/')}"
        async with self._session.request(
            request.method,
            url,
            params=_stringify(request.params) if request.params else None,
            json=request.json,
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
