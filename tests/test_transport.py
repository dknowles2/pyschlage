from typing import Any, cast

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer
import pytest

from pyschlage.auth import API_KEY, Auth
from pyschlage.exceptions import NotAuthorizedError, UnknownError
from pyschlage.transport import AiohttpTransport


class StubAuth:
    """An Auth that hands out a token without talking to Cognito."""

    def __init__(self, token: str = "<token>") -> None:
        self.token = token

    async def async_access_token(self) -> str:
        return self.token


class FakeService:
    """A real HTTP server that records requests and serves canned responses."""

    def __init__(self) -> None:
        self.status = 200
        self.body: Any = {"ok": True}
        self.content_type = "application/json"
        self.requests: list[dict[str, Any]] = []

    async def handle(self, request: web.Request) -> web.Response:
        self.requests.append(
            {
                "method": request.method,
                "path": request.path,
                "query": dict(request.query),
                "headers": dict(request.headers),
                "json": await request.json() if request.can_read_body else None,
            }
        )
        return web.Response(
            body=web.json_response(self.body).body,
            status=self.status,
            content_type=self.content_type,
        )


@pytest.fixture
async def service() -> FakeService:
    return FakeService()


@pytest.fixture
async def transport(service: FakeService):
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", service.handle)
    server = TestServer(app)
    await server.start_server()
    async with aiohttp.ClientSession() as session:
        yield AiohttpTransport(
            cast(Auth, StubAuth()),
            session,
            base_url=str(server.make_url("")).rstrip("/"),
        )
    await server.close()


class TestRequest:
    async def test_returns_decoded_json(
        self, transport: AiohttpTransport, service: FakeService
    ) -> None:
        service.body = {"identityId": "abc"}
        assert await transport.request("get", "users/@me") == {"identityId": "abc"}

    async def test_sends_auth_headers(
        self, transport: AiohttpTransport, service: FakeService
    ) -> None:
        await transport.request("get", "users/@me")
        headers = service.requests[0]["headers"]
        assert headers["Authorization"] == "Bearer <token>"
        assert headers["X-Api-Key"] == API_KEY

    async def test_strips_leading_slash(
        self, transport: AiohttpTransport, service: FakeService
    ) -> None:
        await transport.request("get", "/devices")
        assert service.requests[0]["path"] == "/devices"

    async def test_stringifies_params(
        self, transport: AiohttpTransport, service: FakeService
    ) -> None:
        await transport.request("get", "devices", params={"limit": 10, "sort": "desc"})
        assert service.requests[0]["query"] == {"limit": "10", "sort": "desc"}

    async def test_sends_json_body(
        self, transport: AiohttpTransport, service: FakeService
    ) -> None:
        await transport.request("put", "devices/abc", json={"attributes": {"a": 1}})
        assert service.requests[0]["json"] == {"attributes": {"a": 1}}

    async def test_tolerates_wrong_content_type(
        self, transport: AiohttpTransport, service: FakeService
    ) -> None:
        service.content_type = "text/plain"
        service.body = {"ok": True}
        assert await transport.request("get", "devices") == {"ok": True}


class TestErrors:
    @pytest.mark.parametrize("status", [401, 403])
    async def test_not_authorized(
        self, transport: AiohttpTransport, service: FakeService, status: int
    ) -> None:
        service.status = status
        service.body = {"message": "nope"}
        with pytest.raises(NotAuthorizedError, match="nope"):
            await transport.request("get", "devices")

    async def test_unknown_error_uses_message(
        self, transport: AiohttpTransport, service: FakeService
    ) -> None:
        service.status = 500
        service.body = {"message": "boom"}
        with pytest.raises(UnknownError, match="boom"):
            await transport.request("get", "devices")

    async def test_unknown_error_without_message(
        self, transport: AiohttpTransport, service: FakeService
    ) -> None:
        service.status = 500
        service.body = ["not", "a", "dict"]
        with pytest.raises(UnknownError):
            await transport.request("get", "devices")
