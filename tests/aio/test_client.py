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
from pyschlage.device import AlarmMode
from pyschlage.exceptions import UnknownError
from pyschlage.lock import LockStateMetadata
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
        response = self.responses.pop(0) if self.responses else None
        if isinstance(response, Exception):
            raise response
        return response

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

    async def test_get_lock_keeps_who_changed_it_across_a_poll(
        self,
        schlage: Schlage,
        transport: FakeTransport,
        wifi_lock_json: dict[str, Any],
        wifi_lock_snapshot: Lock,
    ) -> None:
        before = wifi_lock_snapshot.lock_state_metadata
        assert before is not None and before.action_type != "deepQuery"
        wifi_lock_json["attributes"]["lockStateMetadata"] = {
            "actionType": "deepQuery",
            "UUID": None,
            "name": None,
        }
        transport.returns(wifi_lock_json)
        lock = await schlage.get_lock(wifi_lock_snapshot)
        assert lock.lock_state_metadata == before
        assert lock.last_changed_by() == wifi_lock_snapshot.last_changed_by()

    async def test_get_lock_by_id_takes_the_poll_as_reported(
        self,
        schlage: Schlage,
        transport: FakeTransport,
        wifi_lock_json: dict[str, Any],
    ) -> None:
        # With only an id there is no earlier state to keep.
        wifi_lock_json["attributes"]["lockStateMetadata"] = {
            "actionType": "deepQuery",
            "UUID": None,
            "name": None,
        }
        transport.returns(wifi_lock_json)
        lock = await schlage.get_lock("__wifi_uuid__")
        assert lock.lock_state_metadata == LockStateMetadata(
            action_type="deepQuery", uuid=None, name=None
        )
        assert lock.last_changed_by() is None

    async def test_settings_write_keeps_who_changed_it_across_a_poll(
        self,
        schlage: Schlage,
        transport: FakeTransport,
        wifi_lock_json: dict[str, Any],
        wifi_lock_snapshot: Lock,
    ) -> None:
        before = wifi_lock_snapshot.lock_state_metadata
        wifi_lock_json["attributes"]["lockStateMetadata"] = {
            "actionType": "deepQuery",
            "UUID": None,
            "name": None,
        }
        transport.returns(wifi_lock_json)
        lock = await schlage.set_beeper(wifi_lock_snapshot, True)
        assert lock.lock_state_metadata == before

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
        transport.returns(
            {"result": {"state": 0, "batteryLevel": 40, "alarmSelection": 0}}
        )
        lock = await schlage.set_locked(ble_lock_snapshot, False)
        # The snapshot reflects what the lock reported, not what was asked.
        assert lock.is_locked is False
        assert lock.is_jammed is False
        assert lock.battery_level == 40
        assert lock.alarm_mode == AlarmMode.DISABLED
        assert transport.request == request.change_lock_state(
            "__ble_uuid__", cat="abcdef", user_id=USER_ID, lock_state=0
        )

    async def test_set_locked_bridge_keeps_what_the_reply_omits(
        self, schlage: Schlage, transport: FakeTransport, ble_lock_snapshot: Lock
    ) -> None:
        transport.returns({"result": {}})
        lock = await schlage.set_locked(ble_lock_snapshot, False)
        assert lock == ble_lock_snapshot

    async def test_set_locked_bridge_failure_raises(
        self, schlage: Schlage, transport: FakeTransport, ble_lock_snapshot: Lock
    ) -> None:
        transport.returns(
            {"result": None, "error": {"message": "lock offline", "statusCode": 504}}
        )
        with pytest.raises(UnknownError, match="lock offline") as excinfo:
            await schlage.set_locked(ble_lock_snapshot, False)
        assert excinfo.value.status_code == 504

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

    async def test_set_auto_lock_time_is_validated_per_model(
        self,
        schlage: Schlage,
        transport: FakeTransport,
        wifi_lock_json: dict[str, Any],
        wifi_lock_snapshot: Lock,
    ) -> None:
        # 300 seconds is an Encode Plus delay, so an Encode refuses it even
        # though some model accepts it.
        with pytest.raises(ValueError, match="auto_lock_time must be one of"):
            await schlage.set_auto_lock_time(wifi_lock_snapshot, 300)
        assert transport.requests == []

        encode_plus = replace(wifi_lock_snapshot, device_type="be499wifi")
        transport.returns(wifi_lock_json)
        await schlage.set_auto_lock_time(encode_plus, 300)
        assert transport.request == request.put_lock_attributes(
            "__wifi_uuid__", {"autoLockTime": 300}
        )


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
            request.get_access_codes("__wifi_uuid__", limit=100),
        ]

    async def test_get_access_codes_asks_for_the_lock_s_capacity(
        self,
        schlage: Schlage,
        transport: FakeTransport,
        wifi_lock_snapshot: Lock,
    ) -> None:
        lock = replace(wifi_lock_snapshot, max_user_codes=30)
        transport.returns([], [])
        await schlage.get_access_codes(lock)
        assert transport.requests[1] == request.get_access_codes(
            "__wifi_uuid__", limit=30
        )

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

    async def test_notification_update_falls_back_to_create_on_404(
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
        transport.returns(None, UnknownError("gone", status_code=404), None)
        await schlage.update_access_code(code)
        _, update, create = transport.requests
        assert update.method == "put"
        assert update.path == "notifications/<user-id>___access_code_uuid__"
        assert create.method == "post"
        assert create.path == "notifications"

    async def test_notification_create_replaces_a_stale_copy_on_409(
        self, schlage: Schlage, transport: FakeTransport, wifi_lock_snapshot: Lock
    ) -> None:
        transport.returns(
            {"accesscodeId": "__new_code__"},
            UnknownError("exists", status_code=409),
            None,
            None,
        )
        new_code = NewAccessCode(name="New code", code="1234", notify_on_use=True)
        await schlage.add_access_code(wifi_lock_snapshot, new_code)
        _, first, delete, second = transport.requests
        assert first.method == second.method == "post"
        assert first == second
        assert delete == request.delete_notification(f"{USER_ID}___new_code__")

    @pytest.mark.parametrize("status_code", [409, 500])
    async def test_notification_update_reraises_other_errors(
        self,
        schlage: Schlage,
        transport: FakeTransport,
        access_code_json: dict[str, Any],
        notification_json: dict[str, Any],
        status_code: int,
    ) -> None:
        code = AccessCode.from_json(
            access_code_json,
            device_id="__wifi_uuid__",
            device_type="be489wifi",
            notification=Notification.from_json(notification_json),
        )
        transport.returns(None, UnknownError("boom", status_code=status_code))
        with pytest.raises(UnknownError, match="boom"):
            await schlage.update_access_code(code)
        assert len(transport.requests) == 2

    @pytest.mark.parametrize("status_code", [404, 500])
    async def test_notification_create_reraises_other_errors(
        self,
        schlage: Schlage,
        transport: FakeTransport,
        wifi_lock_snapshot: Lock,
        status_code: int,
    ) -> None:
        transport.returns(
            {"accesscodeId": "__new_code__"},
            UnknownError("boom", status_code=status_code),
        )
        new_code = NewAccessCode(name="New code", code="1234", notify_on_use=True)
        with pytest.raises(UnknownError, match="boom"):
            await schlage.add_access_code(wifi_lock_snapshot, new_code)
        assert len(transport.requests) == 2

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
