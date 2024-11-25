from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any
from unittest.mock import Mock, call, patch

import pytest

from pyschlage.code import AccessCode
from pyschlage.exceptions import NotAuthenticatedError
from pyschlage.lock import Lock
from pyschlage.log import LockLog
from pyschlage.notification import Notification
from pyschlage.user import User


class TestLock:
    def test_from_json(self, mock_auth, lock_json):
        lock = Lock.from_json(mock_auth, lock_json)
        assert lock._auth == mock_auth
        assert lock.device_id == "__wifi_uuid__"
        assert lock.name == "Door Lock"
        assert lock.model_name == "__model_name__"
        assert lock.device_type == "be489wifi"
        assert lock.connected is True
        assert lock.battery_level == 95
        assert lock.is_locked
        assert lock._cat == "01234"
        assert lock.is_jammed is False
        assert lock.beeper_enabled is True
        assert lock.lock_and_leave_enabled is True
        assert lock.auto_lock_time == 0
        assert lock.firmware_version == "10.00.00264232"
        assert lock.mac_address == "AA:BB:CC:00:11:22"
        assert lock.users == {
            "user-uuid": User("asdf", "asdf@asdf.com", "user-uuid"),
            "foo-bar-uuid": User("Foo Bar", "foo@bar.xyz", "foo-bar-uuid"),
        }

    def test_from_json_cat_optional(
        self, mock_auth: Mock, lock_json: dict[Any, Any]
    ) -> None:
        lock_json.pop("CAT", None)
        lock = Lock.from_json(mock_auth, lock_json)
        assert lock._cat == ""

    def test_from_json_no_connected(
        self, mock_auth: Mock, lock_json: dict[Any, Any]
    ) -> None:
        lock_json.pop("connected")
        lock = Lock.from_json(mock_auth, lock_json)
        assert not lock.connected

    def test_from_json_is_jammed(self, mock_auth, lock_json):
        lock_json["attributes"]["lockState"] = 2
        lock = Lock.from_json(mock_auth, lock_json)
        assert lock.is_locked is False
        assert lock.is_jammed

    def test_from_json_wifi_lock_unavailable(
        self, mock_auth, wifi_lock_unavailable_json
    ):
        lock = Lock.from_json(mock_auth, wifi_lock_unavailable_json)
        assert lock.battery_level is None
        assert lock.firmware_version is None
        assert lock.is_locked is None
        assert lock.is_jammed is None

    def test_from_json_no_model_name(
        self, mock_auth: Mock, lock_json: dict[Any, Any]
    ) -> None:
        lock_json.pop("modelName", None)
        lock = Lock.from_json(mock_auth, lock_json)
        assert lock.model_name == ""

    def test_diagnostics(self, mock_auth: Mock, lock_json: dict) -> None:
        lock = Lock.from_json(mock_auth, lock_json)
        want = {
            "CAT": "<REDACTED>",
            "SAT": "<REDACTED>",
            "attributes": {
                "CAT": "<REDACTED>",
                "SAT": "<REDACTED>",
                "accessCodeLength": 4,
                "actAlarmBuzzerEnabled": 0,
                "actAlarmState": 0,
                "actuationCurrentMax": 226,
                "alarmSelection": 0,
                "alarmSensitivity": 0,
                "alarmState": 0,
                "autoLockTime": 0,
                "batteryChangeDate": 1669017530,
                "batteryLevel": 95,
                "batteryLowState": 0,
                "batterySaverConfig": {"activePeriod": [], "enabled": 0},
                "batterySaverState": 0,
                "beeperEnabled": 1,
                "bleFirmwareVersion": "0118.000103.015",
                "diagnostics": {},
                "firmwareUpdate": {
                    "status": {"additionalInfo": None, "updateStatus": None}
                },
                "homePosCurrentMax": 153,
                "keypadFirmwareVersion": "03.00.00250052",
                "lockAndLeaveEnabled": 1,
                "lockState": 1,
                "lockStateMetadata": {
                    "UUID": None,
                    "actionType": "periodicDeepQuery",
                    "clientId": None,
                    "name": None,
                },
                "macAddress": "<REDACTED>",
                "mainFirmwareVersion": "10.00.00264232",
                "mode": 2,
                "modelName": "__model_name__",
                "periodicDeepQueryTimeSetting": 60,
                "psPollEnabled": 1,
                "serialNumber": "<REDACTED>",
                "timezone": -20,
                "wifiFirmwareVersion": "03.15.00.01",
                "wifiRssi": -42,
            },
            "connected": True,
            "connectivityUpdated": "2022-12-04T20:58:22.000Z",
            "created": "2020-04-05T21:53:11.000Z",
            "deviceId": "<REDACTED>",
            "devicetypeId": "be489wifi",
            "lastUpdated": "2022-12-04T20:58:22.000Z",
            "macAddress": "<REDACTED>",
            "modelName": "__model_name__",
            "name": "Door Lock",
            "physicalId": "<REDACTED>",
            "relatedDevices": ["<REDACTED>"],
            "role": "owner",
            "serialNumber": "<REDACTED>",
            "timezone": -20,
            "users": ["<REDACTED>"],
        }
        assert lock.get_diagnostics() == want

    def test_refresh(
        self,
        mock_auth: Mock,
        lock_json: dict[str, Any],
        access_code_json: dict[str, Any],
        notification_json: dict[str, Any],
    ) -> None:
        with pytest.raises(NotAuthenticatedError):
            Lock().refresh()
        lock = Lock.from_json(mock_auth, lock_json)
        lock_json["name"] = "<NAME>"

        mock_auth.request.side_effect = [
            Mock(json=Mock(return_value=lock_json)),
            Mock(json=Mock(return_value=[notification_json])),
            Mock(json=Mock(return_value=[access_code_json])),
        ]
        lock.refresh()

        mock_auth.request.assert_has_calls(
            [
                call("get", "devices/__wifi_uuid__"),
                call(
                    "get", "notifications", params={"deviceId": lock_json["deviceId"]}
                ),
                call("get", "devices/__wifi_uuid__/storage/accesscode"),
            ]
        )
        assert lock.name == "<NAME>"

    def test_send_command_unauthenticated(self):
        with pytest.raises(NotAuthenticatedError):
            Lock().send_command("foo", data={"bar": "baz"})

    def test_lock_wifi(self, mock_auth, wifi_lock_json):
        initial_json = deepcopy(wifi_lock_json)
        initial_json["attributes"]["lockState"] = 0
        lock = Lock.from_json(mock_auth, initial_json)

        new_json = deepcopy(wifi_lock_json)
        new_json["attributes"]["lockState"] = 1

        mock_auth.request.return_value = Mock(json=Mock(return_value=new_json))
        lock.lock()

        mock_auth.request.assert_called_once_with(
            "put", "devices/__wifi_uuid__", json={"attributes": {"lockState": 1}}
        )
        assert lock.is_locked

    def test_unlock_wifi(self, mock_auth, wifi_lock_json):
        initial_json = deepcopy(wifi_lock_json)
        initial_json["attributes"]["lockState"] = 1
        lock = Lock.from_json(mock_auth, initial_json)

        new_json = deepcopy(wifi_lock_json)
        new_json["attributes"]["lockState"] = 0

        mock_auth.request.return_value = Mock(json=Mock(return_value=new_json))
        lock.unlock()

        mock_auth.request.assert_called_once_with(
            "put", "devices/__wifi_uuid__", json={"attributes": {"lockState": 0}}
        )
        assert not lock.is_locked

    def test_lock_ble(self, mock_auth, ble_lock_json):
        with pytest.raises(NotAuthenticatedError):
            Lock().lock()

        lock = Lock.from_json(mock_auth, ble_lock_json)
        lock.lock()

        command_json = {
            "data": {
                "CAT": "abcdef",
                "deviceId": "__ble_uuid__",
                "state": 1,
                "userId": "<user-id>",
            },
            "name": "changelockstate",
        }
        mock_auth.request.assert_called_once_with(
            "post", "devices/__ble_uuid__/commands", json=command_json
        )
        assert lock.is_locked

    def test_unlock_ble(self, mock_auth, ble_lock_json):
        with pytest.raises(NotAuthenticatedError):
            Lock().unlock()

        lock = Lock.from_json(mock_auth, ble_lock_json)
        lock.unlock()

        command_json = {
            "data": {
                "CAT": "abcdef",
                "deviceId": "__ble_uuid__",
                "state": 0,
                "userId": "<user-id>",
            },
            "name": "changelockstate",
        }
        mock_auth.request.assert_called_once_with(
            "post", "devices/__ble_uuid__/commands", json=command_json
        )
        assert not lock.is_locked

    def test_logs(
        self,
        mock_auth: Mock,
        wifi_lock: Lock,
        log_json: dict[str, Any],
        lock_log: LockLog,
    ):
        with pytest.raises(NotAuthenticatedError):
            Lock().logs()

        mock_auth.request.return_value = Mock(json=Mock(return_value=[log_json]))
        assert wifi_lock.logs(limit=10, sort_desc=True) == [lock_log]
        mock_auth.request.assert_called_once_with(
            "get", "devices/__wifi_uuid__/logs", params={"limit": 10, "sort": "desc"}
        )

        mock_auth.reset_mock()
        mock_auth.request.return_value = Mock(json=Mock(return_value=[log_json]))
        assert wifi_lock.logs() == [lock_log]
        mock_auth.request.assert_called_once_with(
            "get", "devices/__wifi_uuid__/logs", params={}
        )

    def test_refresh_access_codes(
        self,
        mock_auth: Mock,
        lock_json: dict[str, Any],
        access_code_json: dict[str, Any],
        notification_json: dict[str, Any],
        notification: Notification,
    ) -> None:
        with pytest.raises(NotAuthenticatedError):
            Lock().refresh_access_codes()
        lock = Lock.from_json(mock_auth, lock_json)

        mock_auth.request.side_effect = [
            Mock(json=Mock(return_value=[notification_json])),
            Mock(json=Mock(return_value=[access_code_json])),
        ]
        lock.refresh_access_codes()

        mock_auth.request.assert_has_calls(
            [
                call("get", "notifications", params={"deviceId": lock.device_id}),
                call("get", "devices/__wifi_uuid__/storage/accesscode"),
            ]
        )
        notification.device_type = lock.device_type
        want_code = AccessCode.from_json(mock_auth, lock, access_code_json)
        want_code.device_id = lock.device_id
        want_code._notification = notification
        assert lock.access_codes == {
            access_code_json["accesscodeId"]: want_code,
        }

    def test_add_access_code(
        self,
        mock_auth: Mock,
        lock_json: dict[str, Any],
        access_code_json: dict[str, Any],
        notification_json: dict[str, Any],
    ):
        lock = Lock.from_json(mock_auth, lock_json)
        code = AccessCode.from_json(mock_auth, lock, access_code_json)
        # Users should not set these.
        code._auth = None
        code._device = None
        code.access_code_id = None
        code.device_id = None
        json = code.to_json()

        notification_json["active"] = False
        mock_auth.request.side_effect = [
            Mock(json=Mock(return_value=access_code_json)),
            Mock(json=Mock(return_value=notification_json)),
        ]
        lock.add_access_code(code)

        del notification_json["createdAt"]
        del notification_json["updatedAt"]
        mock_auth.request.assert_has_calls(
            [
                call(
                    "post",
                    "devices/__wifi_uuid__/commands",
                    json={"data": json, "name": "addaccesscode"},
                ),
                call(
                    "post",
                    "notifications/<user-id>___access_code_uuid__",
                    notification_json,
                ),
            ]
        )
        assert code._auth == mock_auth
        assert code.device_id == lock.device_id
        assert code.access_code_id == "__access_code_uuid__"

    def test_set_beeper(
        self, mock_auth: Mock, wifi_lock_json: dict[str, Any], wifi_lock: Lock
    ) -> None:
        assert wifi_lock.beeper_enabled
        wifi_lock_json["attributes"]["beeperEnabled"] = 0
        mock_auth.request.return_value = Mock(json=Mock(return_value=wifi_lock_json))
        wifi_lock.set_beeper(False)
        mock_auth.request.assert_called_once_with(
            "put", "devices/__wifi_uuid__", json={"attributes": {"beeperEnabled": 0}}
        )
        assert not wifi_lock.beeper_enabled

    def test_set_lock_and_leave(
        self, mock_auth: Mock, wifi_lock_json: dict[str, Any], wifi_lock: Lock
    ) -> None:
        assert wifi_lock.lock_and_leave_enabled
        wifi_lock_json["attributes"]["lockAndLeaveEnabled"] = 0
        mock_auth.request.return_value = Mock(json=Mock(return_value=wifi_lock_json))
        wifi_lock.set_lock_and_leave(False)
        mock_auth.request.assert_called_once_with(
            "put",
            "devices/__wifi_uuid__",
            json={"attributes": {"lockAndLeaveEnabled": 0}},
        )
        assert not wifi_lock.lock_and_leave_enabled

    def test_set_auto_lock_time(
        self, mock_auth: Mock, wifi_lock_json: dict[str, Any], wifi_lock: Lock
    ) -> None:
        with pytest.raises(ValueError):
            wifi_lock.set_auto_lock_time(1)

        assert wifi_lock.auto_lock_time == 0
        wifi_lock_json["attributes"]["autoLockTime"] = 15
        mock_auth.request.return_value = Mock(json=Mock(return_value=wifi_lock_json))
        wifi_lock.set_auto_lock_time(15)
        mock_auth.request.assert_called_once_with(
            "put",
            "devices/__wifi_uuid__",
            json={"attributes": {"autoLockTime": 15}},
        )
        assert wifi_lock.auto_lock_time == 15


class TestKeypadDisabled:
    def test_true(self, wifi_lock: Lock) -> None:
        logs = [
            LockLog(
                created_at=datetime(2023, 1, 1, 0, 0, 0),
                message="Unlocked by keypad",
            ),
            LockLog(
                created_at=datetime(2023, 1, 1, 1, 0, 0),
                message="Keypad disabled invalid code",
            ),
        ]
        assert wifi_lock.keypad_disabled(logs) is True

    def test_true_unsorted(self, wifi_lock: Lock) -> None:
        logs = [
            LockLog(
                created_at=datetime(2023, 1, 1, 1, 0, 0),
                message="Keypad disabled invalid code",
            ),
            LockLog(
                created_at=datetime(2023, 1, 1, 0, 0, 0),
                message="Unlocked by keypad",
            ),
        ]
        assert wifi_lock.keypad_disabled(logs) is True

    def test_false(self, wifi_lock: Lock) -> None:
        logs = [
            LockLog(
                created_at=datetime(2023, 1, 1, 0, 0, 0),
                message="Keypad disabled invalid code",
            ),
            LockLog(
                created_at=datetime(2023, 1, 1, 1, 0, 0),
                message="Unlocked by keypad",
            ),
        ]
        assert wifi_lock.keypad_disabled(logs) is False

    def test_fetches_logs(self, wifi_lock: Mock) -> None:
        with patch.object(wifi_lock, "logs") as logs_mock:
            logs_mock.return_value = [
                LockLog(
                    created_at=datetime(2023, 1, 1, 0, 0, 0),
                    message="Unlocked by keypad",
                ),
                LockLog(
                    created_at=datetime(2023, 1, 1, 1, 0, 0),
                    message="Keypad disabled invalid code",
                ),
            ]
            assert wifi_lock.keypad_disabled() is True
            wifi_lock.logs.assert_called_once_with()

    def test_fetches_logs_no_logs(self, wifi_lock: Lock) -> None:
        with patch.object(wifi_lock, "logs") as logs_mock:
            logs_mock.return_value = []
            assert wifi_lock.keypad_disabled() is False
            logs_mock.assert_called_once_with()


class TestChangedBy:
    def test_thumbturn(self, wifi_lock: Lock) -> None:
        assert wifi_lock.lock_state_metadata is not None
        wifi_lock.lock_state_metadata.action_type = "thumbTurn"
        assert wifi_lock.last_changed_by() == "thumbturn"

    def test_one_touch_locking(self, wifi_lock: Lock) -> None:
        assert wifi_lock.lock_state_metadata is not None
        wifi_lock.lock_state_metadata.action_type = "1touchLocking"
        assert wifi_lock.last_changed_by() == "1-touch locking"

    def test_nfc_device(self, wifi_lock: Lock) -> None:
        assert wifi_lock.lock_state_metadata is not None
        wifi_lock.lock_state_metadata.action_type = "AppleHomeNFC"
        wifi_lock.lock_state_metadata.uuid = "user-uuid"
        assert wifi_lock.last_changed_by() == "apple nfc device - asdf"

    def test_nfc_device_no_uuid(self, wifi_lock: Lock) -> None:
        assert wifi_lock.lock_state_metadata is not None
        wifi_lock.lock_state_metadata.action_type = "AppleHomeNFC"
        wifi_lock.lock_state_metadata.uuid = None
        assert wifi_lock.last_changed_by() == "apple nfc device"

    def test_keypad(self, wifi_lock: Lock) -> None:
        assert wifi_lock.lock_state_metadata is not None
        wifi_lock.lock_state_metadata.action_type = "accesscode"
        wifi_lock.lock_state_metadata.name = "secret code"
        assert wifi_lock.last_changed_by() == "keypad - secret code"

    def test_mobile_device(self, wifi_lock: Lock) -> None:
        assert wifi_lock.lock_state_metadata is not None
        wifi_lock.lock_state_metadata.action_type = "virtualKey"
        wifi_lock.lock_state_metadata.uuid = "user-uuid"
        assert wifi_lock.last_changed_by() == "mobile device - asdf"

        wifi_lock.lock_state_metadata.uuid = "unknown"
        assert wifi_lock.last_changed_by() == "mobile device"

        wifi_lock.lock_state_metadata.uuid = None
        assert wifi_lock.last_changed_by() == "mobile device"

    def test_unknown(self, wifi_lock: Lock) -> None:
        assert wifi_lock.last_changed_by() == "unknown"

    def test_no_metadata(self, wifi_lock: Lock) -> None:
        wifi_lock.lock_state_metadata = None
        assert wifi_lock.last_changed_by() is None
