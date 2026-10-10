"""Tests for the asynchronous API client."""

from dataclasses import replace
from typing import Any
from unittest import mock

import pytest

from pyschlage import request
from pyschlage.aio.client import Schlage, connect
from pyschlage.aio.code import AccessCode, NewAccessCode
from pyschlage.aio.lock import Lock
from pyschlage.aio.notification import Notification
from pyschlage.log import KEYPAD_DISABLED_INVALID_CODE
from pyschlage.notification import ON_BATTERY_LOW, ON_UNLOCK_ACTION
from pyschlage.request import Request

USER_ID = "<user-id>"


class FakeTransport:
    """A Transport that records requests and serves canned responses."""

    def __init__(self) -> None:
        self.requests: list[Request] = []
        self.responses: list[Any] = []

    def returns(self, *responses: Any) -> None:
        self.responses = list(responses)

    async def send(self, req: Request) -> Any:
        self.requests.append(req)
        return self.responses.pop(0) if self.responses else None

    @property
    def request(self) -> Request:
        assert len(self.requests) == 1
        return self.requests[0]


@pytest.fixture
def transport() -> FakeTransport:
    return FakeTransport()


@pytest.fixture
def schlage(transport: FakeTransport) -> Schlage:
    return Schlage(transport, USER_ID)


@pytest.fixture
def wifi_lock_snapshot(wifi_lock_json: dict[str, Any]) -> Lock:
    return Lock.from_json(wifi_lock_json)


@pytest.fixture
def ble_lock_snapshot(ble_lock_json: dict[str, Any]) -> Lock:
    return Lock.from_json(ble_lock_json)


@pytest.fixture
def access_code_snapshot(access_code_json: dict[str, Any]) -> AccessCode:
    return AccessCode.from_json(
        access_code_json, device_id="__wifi_uuid__", device_type="be489wifi"
    )


class TestConstruction:
    async def test_from_transport(self, transport: FakeTransport) -> None:
        transport.returns({"identityId": USER_ID})
        schlage = await Schlage.from_transport(transport)
        assert schlage.user_id == USER_ID
        assert transport.request == request.get_current_user()

    async def test_authenticate_with_given_session(
        self, transport: FakeTransport
    ) -> None:
        transport.returns({"identityId": USER_ID})
        session = mock.AsyncMock()
        with (
            mock.patch("pyschlage.aio.client.Auth"),
            mock.patch("pyschlage.aio.client.AiohttpTransport", return_value=transport),
        ):
            schlage = await Schlage.authenticate("user", "pass", session=session)
        assert schlage.user_id == USER_ID
        # The session was not ours, so closing the client leaves it open.
        await schlage.close()
        session.close.assert_not_called()

    async def test_authenticate_owns_the_session_it_creates(
        self, transport: FakeTransport
    ) -> None:
        transport.returns({"identityId": USER_ID})
        session = mock.AsyncMock()
        with (
            mock.patch("pyschlage.aio.client.Auth"),
            mock.patch("pyschlage.aio.client.AiohttpTransport", return_value=transport),
            mock.patch("aiohttp.ClientSession", return_value=session),
        ):
            schlage = await Schlage.authenticate("user", "pass")
        await schlage.close()
        session.close.assert_awaited_once()
        # Closing twice is harmless.
        await schlage.close()
        session.close.assert_awaited_once()

    async def test_authenticate_closes_its_session_on_failure(self) -> None:
        session = mock.AsyncMock()
        with (
            mock.patch("pyschlage.aio.client.Auth"),
            mock.patch("pyschlage.aio.client.AiohttpTransport"),
            mock.patch("aiohttp.ClientSession", return_value=session),
            mock.patch.object(
                Schlage, "_fetch_user_id", side_effect=RuntimeError("boom")
            ),
            pytest.raises(RuntimeError),
        ):
            await Schlage.authenticate("user", "pass")
        session.close.assert_awaited_once()

    async def test_authenticate_leaves_a_given_session_open_on_failure(self) -> None:
        session = mock.AsyncMock()
        with (
            mock.patch("pyschlage.aio.client.Auth"),
            mock.patch("pyschlage.aio.client.AiohttpTransport"),
            mock.patch.object(
                Schlage, "_fetch_user_id", side_effect=RuntimeError("boom")
            ),
            pytest.raises(RuntimeError),
        ):
            await Schlage.authenticate("user", "pass", session=session)
        session.close.assert_not_called()

    async def test_async_context_manager(self, transport: FakeTransport) -> None:
        session = mock.AsyncMock()
        async with Schlage(transport, USER_ID, _owned_session=session) as schlage:
            assert schlage.user_id == USER_ID
        session.close.assert_awaited_once()

    async def test_connect(self, transport: FakeTransport) -> None:
        transport.returns({"identityId": USER_ID})
        session = mock.AsyncMock()
        with (
            mock.patch("pyschlage.aio.client.Auth"),
            mock.patch("pyschlage.aio.client.AiohttpTransport", return_value=transport),
            mock.patch("aiohttp.ClientSession", return_value=session),
        ):
            async with connect("user", "pass") as schlage:
                assert schlage.user_id == USER_ID
        session.close.assert_awaited_once()


class TestLocks:
    async def test_get_locks(
        self,
        schlage: Schlage,
        transport: FakeTransport,
        wifi_lock_json: dict[str, Any],
    ) -> None:
        transport.returns([wifi_lock_json])
        locks = await schlage.get_locks()
        assert locks == [Lock.from_json(wifi_lock_json)]
        assert transport.request == request.get_locks()

    async def test_get_lock(
        self,
        schlage: Schlage,
        transport: FakeTransport,
        wifi_lock_json: dict[str, Any],
    ) -> None:
        transport.returns(wifi_lock_json)
        lock = await schlage.get_lock("__wifi_uuid__")
        assert lock.device_id == "__wifi_uuid__"
        assert transport.request == request.get_lock("__wifi_uuid__")

    async def test_get_lock_accepts_a_snapshot(
        self,
        schlage: Schlage,
        transport: FakeTransport,
        wifi_lock_json: dict[str, Any],
        wifi_lock_snapshot: Lock,
    ) -> None:
        transport.returns(wifi_lock_json)
        await schlage.get_lock(wifi_lock_snapshot)
        assert transport.request == request.get_lock("__wifi_uuid__")

    async def test_get_users(
        self, schlage: Schlage, transport: FakeTransport, lock_users_json: list[dict]
    ) -> None:
        transport.returns(lock_users_json)
        users = await schlage.get_users()
        assert [u.user_id for u in users] == ["user-uuid", "foo-bar-uuid"]
        assert transport.request == request.get_users()


class TestLockState:
    async def test_set_locked_wifi(
        self,
        schlage: Schlage,
        transport: FakeTransport,
        wifi_lock_json: dict[str, Any],
        wifi_lock_snapshot: Lock,
    ) -> None:
        wifi_lock_json["attributes"]["lockState"] = 0
        transport.returns(wifi_lock_json)
        lock = await schlage.set_locked(wifi_lock_snapshot, False)
        assert lock.is_locked is False
        assert transport.request == request.put_lock_attributes(
            "__wifi_uuid__", {"lockState": 0}
        )

    async def test_set_locked_bridge(
        self, schlage: Schlage, transport: FakeTransport, ble_lock_snapshot: Lock
    ) -> None:
        lock = await schlage.set_locked(ble_lock_snapshot, True)
        # The command response carries no state, so the snapshot reflects what
        # we asked for.
        assert lock.is_locked
        assert lock.is_jammed is False
        assert transport.request == request.change_lock_state(
            "__ble_uuid__", cat="abcdef", user_id=USER_ID, lock_state=1
        )

    async def test_set_beeper(
        self,
        schlage: Schlage,
        transport: FakeTransport,
        wifi_lock_json: dict[str, Any],
        wifi_lock_snapshot: Lock,
    ) -> None:
        transport.returns(wifi_lock_json)
        await schlage.set_beeper(wifi_lock_snapshot, False)
        assert transport.request == request.put_lock_attributes(
            "__wifi_uuid__", {"beeperEnabled": 0}
        )

    async def test_set_lock_and_leave(
        self,
        schlage: Schlage,
        transport: FakeTransport,
        wifi_lock_json: dict[str, Any],
        wifi_lock_snapshot: Lock,
    ) -> None:
        transport.returns(wifi_lock_json)
        await schlage.set_lock_and_leave(wifi_lock_snapshot, True)
        assert transport.request == request.put_lock_attributes(
            "__wifi_uuid__", {"lockAndLeaveEnabled": 1}
        )

    async def test_set_auto_lock_time(
        self,
        schlage: Schlage,
        transport: FakeTransport,
        wifi_lock_json: dict[str, Any],
        wifi_lock_snapshot: Lock,
    ) -> None:
        transport.returns(wifi_lock_json)
        await schlage.set_auto_lock_time(wifi_lock_snapshot, 15)
        assert transport.request == request.put_lock_attributes(
            "__wifi_uuid__", {"autoLockTime": 15}
        )

    async def test_set_auto_lock_time_rejects_other_values(
        self, schlage: Schlage, transport: FakeTransport, wifi_lock_snapshot: Lock
    ) -> None:
        with pytest.raises(ValueError):
            await schlage.set_auto_lock_time(wifi_lock_snapshot, 17)
        assert transport.requests == []


class TestLogs:
    async def test_get_logs(
        self, schlage: Schlage, transport: FakeTransport, log_json: dict[str, Any]
    ) -> None:
        transport.returns([log_json])
        logs = await schlage.get_logs("__wifi_uuid__", limit=10, sort_desc=True)
        assert len(logs) == 1
        assert transport.request == request.get_logs(
            "__wifi_uuid__", limit=10, sort_desc=True
        )

    async def test_keypad_disabled(
        self, schlage: Schlage, transport: FakeTransport, log_json: dict[str, Any]
    ) -> None:
        transport.returns([log_json])
        assert not await schlage.keypad_disabled("__wifi_uuid__")

        log_json["message"]["eventCode"] = KEYPAD_DISABLED_INVALID_CODE
        transport.returns([log_json])
        assert await schlage.keypad_disabled("__wifi_uuid__")


class TestAccessCodes:
    async def test_get_access_codes(
        self,
        schlage: Schlage,
        transport: FakeTransport,
        wifi_lock_snapshot: Lock,
        access_code_json: dict[str, Any],
        notification_json: dict[str, Any],
    ) -> None:
        transport.returns([notification_json], [access_code_json])
        codes = await schlage.get_access_codes(wifi_lock_snapshot)
        assert len(codes) == 1
        assert codes[0].access_code_id == "__access_code_uuid__"
        assert codes[0].device_type == "be489wifi"
        assert codes[0].notify_on_use
        assert transport.requests == [
            request.get_notifications("__wifi_uuid__"),
            request.get_access_codes("__wifi_uuid__"),
        ]

    async def test_get_access_codes_ignores_other_notifications(
        self,
        schlage: Schlage,
        transport: FakeTransport,
        wifi_lock_snapshot: Lock,
        access_code_json: dict[str, Any],
        notification_json: dict[str, Any],
    ) -> None:
        wrong_type = dict(notification_json, notificationDefinitionId=ON_BATTERY_LOW)
        wrong_user = dict(
            notification_json, notificationId="other-user___access_code_uuid__"
        )
        transport.returns([wrong_type, wrong_user], [access_code_json])
        codes = await schlage.get_access_codes(wifi_lock_snapshot)
        assert not codes[0].notify_on_use

    async def test_add_access_code(
        self, schlage: Schlage, transport: FakeTransport, wifi_lock_snapshot: Lock
    ) -> None:
        transport.returns({"accesscodeId": "__new_code__"}, None)
        new_code = NewAccessCode(name="New code", code="1234", notify_on_use=True)
        added = await schlage.add_access_code(wifi_lock_snapshot, new_code)

        assert added.access_code_id == "__new_code__"
        assert added.device_id == "__wifi_uuid__"
        assert added.device_type == "be489wifi"
        assert added.name == "New code"
        assert added.notify_on_use

        command, notification = transport.requests
        assert command == request.send_command(
            "__wifi_uuid__", request.ADD_ACCESS_CODE, new_code.to_json()
        )
        # A code the service has just minted has no notification yet, so one is
        # created rather than updated.
        assert notification.method == "post"
        assert notification.json == {
            "notificationId": f"{USER_ID}___new_code__",
            "devicetypeId": "be489wifi",
            "notificationDefinitionId": ON_UNLOCK_ACTION,
            "active": True,
            "filterValue": "New code",
        }

    async def test_update_access_code(
        self,
        schlage: Schlage,
        transport: FakeTransport,
        access_code_snapshot: AccessCode,
    ) -> None:
        renamed = replace(access_code_snapshot, name="Renamed")
        assert await schlage.update_access_code(renamed) == renamed

        command, notification = transport.requests
        assert command == request.send_command(
            "__wifi_uuid__", request.UPDATE_ACCESS_CODE, renamed.to_json()
        )
        assert notification.json is not None
        assert notification.json["filterValue"] == "Renamed"

    async def test_update_access_code_updates_an_existing_notification(
        self,
        schlage: Schlage,
        transport: FakeTransport,
        access_code_json: dict[str, Any],
        notification_json: dict[str, Any],
    ) -> None:
        code = AccessCode.from_json(
            access_code_json,
            device_id="__wifi_uuid__",
            device_type="be489wifi",
            notification=Notification.from_json(notification_json),
        )
        await schlage.update_access_code(code)
        assert transport.requests[1].method == "put"

    async def test_delete_access_code(
        self,
        schlage: Schlage,
        transport: FakeTransport,
        access_code_snapshot: AccessCode,
    ) -> None:
        await schlage.delete_access_code(access_code_snapshot)
        assert transport.requests == [
            request.send_command(
                "__wifi_uuid__",
                request.DELETE_ACCESS_CODE,
                access_code_snapshot.to_json(),
            )
        ]

    async def test_delete_access_code_deletes_its_notification(
        self,
        schlage: Schlage,
        transport: FakeTransport,
        access_code_json: dict[str, Any],
        notification_json: dict[str, Any],
    ) -> None:
        code = AccessCode.from_json(
            access_code_json,
            device_id="__wifi_uuid__",
            device_type="be489wifi",
            notification=Notification.from_json(notification_json),
        )
        await schlage.delete_access_code(code)
        assert transport.requests[1] == request.delete_notification(
            "<user-id>___access_code_uuid__"
        )
