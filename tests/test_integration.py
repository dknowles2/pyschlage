"""End-to-end smoke: real client -> real AiohttpTransport -> real local server."""

from dataclasses import replace
import json
from typing import Any, cast

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer
import pytest

import pyschlage
from pyschlage.auth import Auth
from pyschlage.transport import AiohttpTransport


class StubAuth:
    async def async_access_token(self) -> str:
        return "tok"


@pytest.fixture
async def stack(wifi_lock_json: dict, access_code_json: dict, notification_json: dict):
    seen: list[tuple[str, str]] = []

    async def handler(request: web.Request) -> web.Response:
        seen.append((request.method, request.path))
        path, method = request.path, request.method
        if path == "/users/@me":
            return web.json_response({"identityId": "<user-id>"})
        if path == "/devices" and method == "GET":
            return web.json_response([wifi_lock_json])
        if path == "/devices/__wifi_uuid__" and method == "PUT":
            unlocked = json.loads(json.dumps(wifi_lock_json))
            unlocked["attributes"]["lockState"] = 0
            return web.json_response(unlocked)
        if path == "/notifications":
            return web.json_response([notification_json])
        if path.startswith("/notifications/") and method == "DELETE":
            return web.json_response({})
        if path == "/devices/__wifi_uuid__/storage/accesscode":
            return web.json_response([access_code_json])
        if path.endswith("/commands"):
            return web.json_response({"accesscodeId": "new-id"})
        return web.json_response({"message": "not found"}, status=404)

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", handler)
    server = TestServer(app)
    await server.start_server()
    async with aiohttp.ClientSession() as session:
        transport = AiohttpTransport(
            cast(Auth, StubAuth()),
            session,
            base_url=str(server.make_url("")).rstrip("/"),
        )
        yield await pyschlage.Schlage.from_transport(transport), seen
    await server.close()


async def test_full_round_trip(stack: Any) -> None:
    schlage, seen = stack
    assert schlage.user_id == "<user-id>"

    locks = await schlage.get_locks()
    assert [lock.name for lock in locks] == ["Door Lock"]
    assert locks[0].is_locked is True

    unlocked = await schlage.set_locked(locks[0], False)
    assert unlocked.is_locked is False
    # The snapshot handed in is untouched.
    assert locks[0].is_locked is True

    codes = await schlage.get_access_codes(locks[0])
    assert [c.name for c in codes] == ["Access code name"]
    assert codes[0].notify_on_use is True

    added = await schlage.add_access_code(
        locks[0], pyschlage.NewAccessCode(name="Guest", code="1234")
    )
    assert added.access_code_id == "new-id"
    assert added.device_type == "be489wifi"

    await schlage.update_access_code(replace(added, name="Dog walker"))
    await schlage.delete_access_code(codes[0])

    diagnostics = locks[0].get_diagnostics()
    assert diagnostics["deviceId"] == "<REDACTED>"
    assert diagnostics["name"] == "Door Lock"

    assert ("GET", "/users/@me") in seen
    assert ("PUT", "/devices/__wifi_uuid__") in seen
