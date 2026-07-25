from dataclasses import replace
from typing import Any
from unittest.mock import patch

import aiohttp
import pytest

from pyschlage.client import Schlage, connect
from pyschlage.code import AccessCode, NewAccessCode
from pyschlage.lock import Lock
from pyschlage.notification import ON_UNLOCK_ACTION
from pyschlage.user import User

from .conftest import USER_ID, FakeTransport, RecordedRequest


@pytest.fixture
def stub_auth_stack():
    """Stubs out Cognito and the user_id round trip made during authenticate."""
    with (
        patch("pycognito.Cognito"),
        patch.object(Schlage, "_fetch_user_id", return_value=USER_ID),
    ):
        yield


class TestConstruction:
    async def test_from_transport_fetches_user_id(
        self, transport: FakeTransport
    ) -> None:
        transport.add("get", "users/@me", {"identityId": "abc"})
        schlage = await Schlage.from_transport(transport)
        assert schlage.user_id == "abc"

    async def test_close_is_a_noop_without_owned_session(
        self, schlage: Schlage
    ) -> None:
        await schlage.close()
        await schlage.close()

    async def test_async_context_manager(self, schlage: Schlage) -> None:
        async with schlage as client:
            assert client is schlage


class TestAuthenticate:
    async def test_creates_and_owns_a_session(self, stub_auth_stack) -> None:
        client = await Schlage.authenticate("user", "password")
        session = client._owned_session
        assert isinstance(session, aiohttp.ClientSession)
        assert client.user_id == USER_ID

        await client.close()
        assert session.closed
        # Closing twice is harmless.
        await client.close()

    async def test_does_not_own_an_injected_session(self, stub_auth_stack) -> None:
        async with aiohttp.ClientSession() as session:
            client = await Schlage.authenticate("user", "password", session=session)
            assert client._owned_session is None
            await client.close()
            assert not session.closed

    async def test_closes_owned_session_when_auth_fails(self) -> None:
        sessions: list[aiohttp.ClientSession] = []
        real_session_cls = aiohttp.ClientSession

        def track(*args, **kwargs):
            sessions.append(real_session_cls(*args, **kwargs))
            return sessions[-1]

        with (
            patch("pycognito.Cognito"),
            patch.object(Schlage, "_fetch_user_id", side_effect=RuntimeError("boom")),
            patch("aiohttp.ClientSession", side_effect=track),
            pytest.raises(RuntimeError, match="boom"),
        ):
            await Schlage.authenticate("user", "password")

        assert sessions and sessions[0].closed

    async def test_does_not_close_injected_session_when_auth_fails(self) -> None:
        async with aiohttp.ClientSession() as session:
            with (
                patch("pycognito.Cognito"),
                patch.object(
                    Schlage, "_fetch_user_id", side_effect=RuntimeError("boom")
                ),
                pytest.raises(RuntimeError),
            ):
                await Schlage.authenticate("user", "password", session=session)
            assert not session.closed


class TestConnect:
    async def test_yields_client_and_closes(self, stub_auth_stack) -> None:
        async with connect("user", "password") as client:
            assert client.user_id == USER_ID
            session = client._owned_session
        assert session is not None and session.closed

    async def test_closes_on_error(self, stub_auth_stack) -> None:
        session = None
        with pytest.raises(RuntimeError, match="inner"):
            async with connect("user", "password") as client:
                session = client._owned_session
                raise RuntimeError("inner")
        assert session is not None and session.closed


class TestGetLocks:
    async def test_get_locks(
        self, schlage: Schlage, transport: FakeTransport, wifi_lock_json: dict
    ) -> None:
        transport.add("get", "devices", [wifi_lock_json])
        locks = await schlage.get_locks()
        assert [lock.device_id for lock in locks] == ["__wifi_uuid__"]
        assert transport.requests == [
            RecordedRequest("get", "devices", {"archetype": "lock"}, None)
        ]

    async def test_get_lock(
        self, schlage: Schlage, transport: FakeTransport, wifi_lock_json: dict
    ) -> None:
        transport.add("get", "devices/__wifi_uuid__", wifi_lock_json)
        lock = await schlage.get_lock("__wifi_uuid__")
        assert lock.name == "Door Lock"

    async def test_get_lock_accepts_a_lock(
        self,
        schlage: Schlage,
        transport: FakeTransport,
        wifi_lock: Lock,
        wifi_lock_json: dict,
    ) -> None:
        transport.add("get", "devices/__wifi_uuid__", wifi_lock_json)
        assert await schlage.get_lock(wifi_lock) == wifi_lock

    async def test_get_users(
        self, schlage: Schlage, transport: FakeTransport, lock_users_json: list[dict]
    ) -> None:
        transport.add("get", "users", lock_users_json)
        assert await schlage.get_users() == [
            User("asdf", "asdf@asdf.com", "user-uuid"),
            User("Foo Bar", "foo@bar.xyz", "foo-bar-uuid"),
        ]


class TestSetLocked:
    async def test_wifi_lock_uses_put(
        self,
        schlage: Schlage,
        transport: FakeTransport,
        wifi_lock: Lock,
        wifi_lock_json: dict,
    ) -> None:
        wifi_lock_json["attributes"]["lockState"] = 0
        transport.add("put", "devices/__wifi_uuid__", wifi_lock_json)
        updated = await schlage.set_locked(wifi_lock, False)
        assert updated.is_locked is False
        assert transport.requests == [
            RecordedRequest(
                "put",
                "devices/__wifi_uuid__",
                None,
                {"attributes": {"lockState": 0}},
            )
        ]

    async def test_wifi_lock_does_not_mutate_input(
        self,
        schlage: Schlage,
        transport: FakeTransport,
        wifi_lock: Lock,
        wifi_lock_json: dict,
    ) -> None:
        wifi_lock_json["attributes"]["lockState"] = 0
        transport.add("put", "devices/__wifi_uuid__", wifi_lock_json)
        await schlage.set_locked(wifi_lock, False)
        assert wifi_lock.is_locked is True

    async def test_ble_lock_uses_command(
        self, schlage: Schlage, transport: FakeTransport, ble_lock: Lock
    ) -> None:
        transport.add("post", "devices/__ble_uuid__/commands", {})
        updated = await schlage.set_locked(ble_lock, False)
        assert transport.requests == [
            RecordedRequest(
                "post",
                "devices/__ble_uuid__/commands",
                None,
                {
                    "data": {
                        "CAT": "abcdef",
                        "deviceId": "__ble_uuid__",
                        "state": 0,
                        "userId": USER_ID,
                    },
                    "name": "changelockstate",
                },
            )
        ]
        # The command response carries no state, so the result is optimistic.
        assert updated.is_locked is False
        assert updated.is_jammed is False


class TestSettings:
    @pytest.mark.parametrize(
        ("method", "arg", "want_attributes"),
        [
            ("set_beeper", False, {"beeperEnabled": 0}),
            ("set_beeper", True, {"beeperEnabled": 1}),
            ("set_lock_and_leave", False, {"lockAndLeaveEnabled": 0}),
            ("set_auto_lock_time", 15, {"autoLockTime": 15}),
        ],
    )
    async def test_puts_attributes(
        self,
        schlage: Schlage,
        transport: FakeTransport,
        wifi_lock: Lock,
        wifi_lock_json: dict,
        method: str,
        arg: Any,
        want_attributes: dict,
    ) -> None:
        transport.add("put", "devices/__wifi_uuid__", wifi_lock_json)
        await getattr(schlage, method)(wifi_lock, arg)
        assert transport.requests[0].json == {"attributes": want_attributes}

    async def test_bad_auto_lock_time(self, schlage: Schlage, wifi_lock: Lock) -> None:
        with pytest.raises(ValueError, match="auto_lock_time must be one of"):
            await schlage.set_auto_lock_time(wifi_lock, 17)


class TestLogs:
    async def test_get_logs(
        self, schlage: Schlage, transport: FakeTransport, log_json: dict
    ) -> None:
        transport.add("get", "devices/__wifi_uuid__/logs", [log_json])
        logs = await schlage.get_logs("__wifi_uuid__")
        assert [log.message for log in logs] == ["Unknown"]
        assert transport.requests[0].params == {}

    async def test_get_logs_with_params(
        self, schlage: Schlage, transport: FakeTransport
    ) -> None:
        transport.add("get", "devices/__wifi_uuid__/logs", [])
        await schlage.get_logs("__wifi_uuid__", limit=10, sort_desc=True)
        assert transport.requests[0].params == {"limit": 10, "sort": "desc"}

    async def test_keypad_disabled(
        self, schlage: Schlage, transport: FakeTransport, log_json: dict
    ) -> None:
        log_json["message"]["eventCode"] = 11
        transport.add("get", "devices/__wifi_uuid__/logs", [log_json])
        assert await schlage.keypad_disabled("__wifi_uuid__") is True


class TestGetAccessCodes:
    async def test_joins_notifications(
        self,
        schlage: Schlage,
        transport: FakeTransport,
        wifi_lock: Lock,
        access_code_json: dict,
        notification_json: dict,
    ) -> None:
        transport.add("get", "notifications", [notification_json])
        transport.add(
            "get", "devices/__wifi_uuid__/storage/accesscode", [access_code_json]
        )
        codes = await schlage.get_access_codes(wifi_lock)
        assert len(codes) == 1
        assert codes[0].notify_on_use is True
        assert codes[0].device_type == "be489wifi"

    async def test_ignores_other_users_notifications(
        self,
        schlage: Schlage,
        transport: FakeTransport,
        wifi_lock: Lock,
        access_code_json: dict,
        notification_json: dict,
    ) -> None:
        notification_json["notificationId"] = "someone-else___access_code_uuid__"
        transport.add("get", "notifications", [notification_json])
        transport.add(
            "get", "devices/__wifi_uuid__/storage/accesscode", [access_code_json]
        )
        codes = await schlage.get_access_codes(wifi_lock)
        assert codes[0].notify_on_use is False

    async def test_ignores_other_notification_types(
        self,
        schlage: Schlage,
        transport: FakeTransport,
        wifi_lock: Lock,
        access_code_json: dict,
        notification_json: dict,
    ) -> None:
        notification_json["notificationDefinitionId"] = "onbatterylowstate"
        transport.add("get", "notifications", [notification_json])
        transport.add(
            "get", "devices/__wifi_uuid__/storage/accesscode", [access_code_json]
        )
        codes = await schlage.get_access_codes(wifi_lock)
        assert codes[0].notify_on_use is False

    async def test_missing_notification(
        self,
        schlage: Schlage,
        transport: FakeTransport,
        wifi_lock: Lock,
        access_code_json: dict,
    ) -> None:
        transport.add("get", "notifications", [])
        transport.add(
            "get", "devices/__wifi_uuid__/storage/accesscode", [access_code_json]
        )
        codes = await schlage.get_access_codes(wifi_lock)
        assert codes[0].notify_on_use is False
        assert codes[0]._notification is None


class TestAddAccessCode:
    async def test_add(
        self, schlage: Schlage, transport: FakeTransport, wifi_lock: Lock
    ) -> None:
        transport.add(
            "post",
            "devices/__wifi_uuid__/commands",
            {"accesscodeId": "new-code-uuid"},
        )
        transport.add("post", "notifications", {})
        code = await schlage.add_access_code(
            wifi_lock, NewAccessCode(name="Guest", code="1234")
        )
        assert code.access_code_id == "new-code-uuid"
        assert code.device_id == "__wifi_uuid__"
        assert code.device_type == "be489wifi"
        assert code.name == "Guest"
        assert code.code == "1234"

    async def test_creates_notification_with_post(
        self, schlage: Schlage, transport: FakeTransport, wifi_lock: Lock
    ) -> None:
        transport.add(
            "post",
            "devices/__wifi_uuid__/commands",
            {"accesscodeId": "new-code-uuid"},
        )
        transport.add("post", "notifications", {})
        await schlage.add_access_code(
            wifi_lock, NewAccessCode(name="Guest", code="1234", notify_on_use=True)
        )
        notification_request = transport.requests[-1]
        assert notification_request.method == "post"
        assert notification_request.json == {
            "notificationId": f"{USER_ID}_new-code-uuid",
            "devicetypeId": "be489wifi",
            "notificationDefinitionId": ON_UNLOCK_ACTION,
            "active": True,
            "filterValue": "Guest",
        }


class TestUpdateAccessCode:
    async def test_update_uses_put_for_existing_notification(
        self,
        schlage: Schlage,
        transport: FakeTransport,
        access_code_json: dict,
        notification_json: dict,
        wifi_lock: Lock,
    ) -> None:
        transport.add("get", "notifications", [notification_json])
        transport.add(
            "get", "devices/__wifi_uuid__/storage/accesscode", [access_code_json]
        )
        code = (await schlage.get_access_codes(wifi_lock))[0]

        transport.add("post", "devices/__wifi_uuid__/commands", {})
        transport.add("put", "notifications", {})
        updated = await schlage.update_access_code(replace(code, name="Renamed"))

        assert updated.name == "Renamed"
        assert transport.requests[-1].method == "put"
        assert transport.requests[-1].json["filterValue"] == "Renamed"

    async def test_update_uses_post_without_existing_notification(
        self, schlage: Schlage, transport: FakeTransport, access_code: AccessCode
    ) -> None:
        transport.add("post", "devices/__wifi_uuid__/commands", {})
        transport.add("post", "notifications", {})
        await schlage.update_access_code(access_code)
        assert transport.requests[-1].method == "post"

    async def test_sends_update_command(
        self, schlage: Schlage, transport: FakeTransport, access_code: AccessCode
    ) -> None:
        transport.add("post", "devices/__wifi_uuid__/commands", {})
        transport.add("post", "notifications", {})
        await schlage.update_access_code(access_code)
        command = transport.requests[0]
        assert command.json["name"] == "updateaccesscode"
        assert command.json["data"]["accesscodeId"] == "__access_code_uuid__"


class TestDeleteAccessCode:
    async def test_delete_without_notification(
        self, schlage: Schlage, transport: FakeTransport, access_code: AccessCode
    ) -> None:
        transport.add("post", "devices/__wifi_uuid__/commands", {})
        await schlage.delete_access_code(access_code)
        assert transport.requests[0].json["name"] == "deleteaccesscode"
        assert len(transport.requests) == 1

    async def test_delete_removes_notification(
        self,
        schlage: Schlage,
        transport: FakeTransport,
        access_code_json: dict,
        notification_json: dict,
        wifi_lock: Lock,
    ) -> None:
        transport.add("get", "notifications", [notification_json])
        transport.add(
            "get", "devices/__wifi_uuid__/storage/accesscode", [access_code_json]
        )
        code = (await schlage.get_access_codes(wifi_lock))[0]

        transport.add("post", "devices/__wifi_uuid__/commands", {})
        transport.add("delete", "notifications/<user-id>___access_code_uuid__", {})
        await schlage.delete_access_code(code)
        assert transport.requests[-1] == RecordedRequest(
            "delete", "notifications/<user-id>___access_code_uuid__", None, None
        )
