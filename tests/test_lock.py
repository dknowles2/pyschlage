from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any
from unittest import mock

import pytest

from pyschlage.code import AccessCode
from pyschlage.lock import Lock
from pyschlage.log import LockLog
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

    def test_from_json_no_connected(
        self, mock_auth: mock.Mock, lock_json: dict[Any, Any]
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

    def test_diagnostics(self, mock_auth: mock.Mock, lock_json: dict) -> None:
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
        self, mock_auth: mock.Mock, lock_json: dict, access_code_json: dict
    ) -> None:
        lock = Lock.from_json(mock_auth, lock_json)
        lock_json["name"] = "<NAME>"

        mock_auth.request.side_effect = [
            mock.Mock(json=mock.Mock(return_value=lock_json)),
            mock.Mock(json=mock.Mock(return_value=[access_code_json])),
        ]
        lock.refresh()

        mock_auth.request.assert_has_calls(
            [
                mock.call("get", "devices/__wifi_uuid__"),
                mock.call("get", "devices/__wifi_uuid__/storage/accesscode"),
            ]
        )
        assert lock.name == "<NAME>"

    def test_lock_wifi(self, mock_auth, wifi_lock_json):
        initial_json = deepcopy(wifi_lock_json)
        initial_json["attributes"]["lockState"] = 0
        lock = Lock.from_json(mock_auth, initial_json)

        new_json = deepcopy(wifi_lock_json)
        new_json["attributes"]["lockState"] = 1

        mock_auth.request.return_value = mock.Mock(
            json=mock.Mock(return_value=new_json)
        )
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

        mock_auth.request.return_value = mock.Mock(
            json=mock.Mock(return_value=new_json)
        )
        lock.unlock()

        mock_auth.request.assert_called_once_with(
            "put", "devices/__wifi_uuid__", json={"attributes": {"lockState": 0}}
        )
        assert lock.is_locked == False

    def test_lock_ble(self, mock_auth, ble_lock_json):
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
        assert lock.is_locked == False

    def test_refresh_access_codes(
        self, mock_auth: mock.Mock, lock_json: dict, access_code_json: dict
    ) -> None:
        lock = Lock.from_json(mock_auth, lock_json)

        mock_auth.request.return_value = mock.Mock(
            json=mock.Mock(return_value=[access_code_json])
        )
        lock.refresh_access_codes()

        mock_auth.request.assert_called_once_with(
            "get", "devices/__wifi_uuid__/storage/accesscode"
        )
        assert lock.access_codes == {
            access_code_json["accesscodeId"]: AccessCode.from_json(
                mock_auth, access_code_json, lock.device_id
            )
        }

    def test_add_access_code(self, mock_auth, lock_json, access_code_json):
        lock = Lock.from_json(mock_auth, lock_json)
        code = AccessCode.from_json(mock_auth, access_code_json, lock.device_id)
        # Users should not set these.
        code._auth = None
        code.access_code_id = None
        code.device_id = None
        json = code.to_json()

        mock_auth.request.return_value = mock.Mock(
            json=mock.Mock(return_value=access_code_json)
        )
        lock.add_access_code(code)

        mock_auth.request.assert_called_once_with(
            "post",
            "devices/__wifi_uuid__/storage/accesscode",
            json=json,
        )
        assert code._auth == mock_auth
        assert code.device_id == lock.device_id
        assert code.access_code_id == "__access_code_uuid__"


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

    def test_fetches_logs(self, wifi_lock: Lock) -> None:
        with mock.patch.object(wifi_lock, "logs") as logs_mock:
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
        with mock.patch.object(wifi_lock, "logs") as logs_mock:
            logs_mock.return_value = []
            assert wifi_lock.keypad_disabled() is False
            wifi_lock.logs.assert_called_once_with()


class TestChangedBy:
    def test_thumbturn(self, wifi_lock: Lock) -> None:
        wifi_lock.lock_state_metadata.action_type = "thumbTurn"
        assert wifi_lock.last_changed_by() == "thumbturn"

    def test_keypad(self, wifi_lock: Lock) -> None:
        wifi_lock.lock_state_metadata.action_type = "accesscode"
        wifi_lock.lock_state_metadata.name = "secret code"
        assert wifi_lock.last_changed_by() == "keypad - secret code"

    def test_mobile_device(self, wifi_lock: Lock) -> None:
        wifi_lock.lock_state_metadata.action_type = "virtualKey"
        wifi_lock.lock_state_metadata.uuid = "user-uuid"
        assert wifi_lock.last_changed_by() == "mobile device - asdf"

    def test_unknown(self, wifi_lock: Lock) -> None:
        assert wifi_lock.last_changed_by() == "unknown"

    def test_no_metadata(self, wifi_lock: Lock) -> None:
        wifi_lock.lock_state_metadata = None
        assert wifi_lock.last_changed_by() is None
