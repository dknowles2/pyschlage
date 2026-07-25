from datetime import datetime
from typing import Any

import pytest

from pyschlage.lock import Lock, LockStateMetadata
from pyschlage.log import LockLog
from pyschlage.user import User


def _log(message: str, created_at: str) -> LockLog:
    return LockLog(created_at=datetime.fromisoformat(created_at), message=message)


class TestLockFromJson:
    def test_from_json(self, wifi_lock_json: dict[str, Any]) -> None:
        lock = Lock.from_json(wifi_lock_json)
        assert lock.device_id == "__wifi_uuid__"
        assert lock.name == "Door Lock"
        assert lock.model_name == "__model_name__"
        assert lock.device_type == "be489wifi"
        assert lock.connected is True
        assert lock.battery_level == 95
        assert lock.is_locked is True
        assert lock.is_jammed is False
        assert lock.beeper_enabled is True
        assert lock.lock_and_leave_enabled is True
        assert lock.auto_lock_time == 0
        assert lock.firmware_version == "10.00.00264232"
        assert lock.mac_address == "AA:BB:CC:00:11:22"
        assert lock._cat == "01234"
        assert lock.users == {
            "user-uuid": User("asdf", "asdf@asdf.com", "user-uuid"),
            "foo-bar-uuid": User("Foo Bar", "foo@bar.xyz", "foo-bar-uuid"),
        }

    def test_from_json_jammed(self, wifi_lock_json: dict[str, Any]) -> None:
        wifi_lock_json["attributes"]["lockState"] = 2
        lock = Lock.from_json(wifi_lock_json)
        assert lock.is_locked is False
        assert lock.is_jammed is True

    def test_from_json_unavailable(
        self, wifi_lock_unavailable_json: dict[str, Any]
    ) -> None:
        lock = Lock.from_json(wifi_lock_unavailable_json)
        assert lock.is_locked is None
        assert lock.is_jammed is None
        assert lock.battery_level is None
        assert lock.firmware_version is None
        assert lock.lock_state_metadata is None

    def test_from_json_cat_optional(self, wifi_lock_json: dict[str, Any]) -> None:
        del wifi_lock_json["CAT"]
        assert Lock.from_json(wifi_lock_json)._cat == ""

    def test_from_json_no_connected(self, wifi_lock_json: dict[str, Any]) -> None:
        del wifi_lock_json["connected"]
        assert Lock.from_json(wifi_lock_json).connected is False

    def test_from_json_no_users(self, wifi_lock_json: dict[str, Any]) -> None:
        del wifi_lock_json["users"]
        assert Lock.from_json(wifi_lock_json).users == {}

    def test_lock_state_metadata(self, wifi_lock_json: dict[str, Any]) -> None:
        assert Lock.from_json(wifi_lock_json).lock_state_metadata == LockStateMetadata(
            action_type="periodicDeepQuery", uuid=None, name=None
        )

    def test_request_path(self) -> None:
        assert Lock.request_path() == "devices"
        assert Lock.request_path("dev") == "devices/dev"


class TestIsWifiLock:
    def test_wifi_lock(self, wifi_lock: Lock) -> None:
        assert wifi_lock.is_wifi_lock is True

    def test_ble_lock(self, ble_lock: Lock) -> None:
        assert ble_lock.is_wifi_lock is False


class TestLastChangedBy:
    def test_no_metadata(self, wifi_lock_unavailable_json: dict[str, Any]) -> None:
        assert Lock.from_json(wifi_lock_unavailable_json).last_changed_by() is None

    @pytest.mark.parametrize(
        ("action_type", "want"),
        [
            ("thumbTurn", "thumbturn"),
            ("1touchLocking", "1-touch locking"),
            ("unhandled", "unknown"),
        ],
    )
    def test_simple_actions(
        self, wifi_lock_json: dict[str, Any], action_type: str, want: str
    ) -> None:
        wifi_lock_json["attributes"]["lockStateMetadata"]["actionType"] = action_type
        assert Lock.from_json(wifi_lock_json).last_changed_by() == want

    def test_access_code(self, wifi_lock_json: dict[str, Any]) -> None:
        metadata = wifi_lock_json["attributes"]["lockStateMetadata"]
        metadata["actionType"] = "accesscode"
        metadata["name"] = "Guest"
        assert Lock.from_json(wifi_lock_json).last_changed_by() == "keypad - Guest"

    def test_virtual_key_with_known_user(self, wifi_lock_json: dict[str, Any]) -> None:
        metadata = wifi_lock_json["attributes"]["lockStateMetadata"]
        metadata["actionType"] = "virtualKey"
        metadata["UUID"] = "user-uuid"
        assert (
            Lock.from_json(wifi_lock_json).last_changed_by() == "mobile device - asdf"
        )

    def test_virtual_key_with_unknown_user(
        self, wifi_lock_json: dict[str, Any]
    ) -> None:
        metadata = wifi_lock_json["attributes"]["lockStateMetadata"]
        metadata["actionType"] = "virtualKey"
        metadata["UUID"] = "nobody"
        assert Lock.from_json(wifi_lock_json).last_changed_by() == "mobile device"

    def test_apple_nfc(self, wifi_lock_json: dict[str, Any]) -> None:
        metadata = wifi_lock_json["attributes"]["lockStateMetadata"]
        metadata["actionType"] = "AppleHomeNFC"
        metadata["UUID"] = "user-uuid"
        assert (
            Lock.from_json(wifi_lock_json).last_changed_by()
            == "apple nfc device - asdf"
        )


class TestKeypadDisabled:
    def test_no_logs(self) -> None:
        assert Lock.keypad_disabled([]) is False

    def test_newest_log_is_disabled(self) -> None:
        logs = [
            _log("Locked by keypad", "2023-03-01T15:00:00.000Z"),
            _log("Keypad disabled invalid code", "2023-03-01T17:00:00.000Z"),
        ]
        assert Lock.keypad_disabled(logs) is True

    def test_ignores_older_disabled_log(self) -> None:
        logs = [
            _log("Keypad disabled invalid code", "2023-03-01T15:00:00.000Z"),
            _log("Unlocked by keypad", "2023-03-01T17:00:00.000Z"),
        ]
        assert Lock.keypad_disabled(logs) is False


class TestDiagnostics:
    def test_redacts_secrets(self, wifi_lock: Lock) -> None:
        diagnostics = wifi_lock.get_diagnostics()
        assert diagnostics["deviceId"] == "<REDACTED>"
        assert diagnostics["serialNumber"] == "<REDACTED>"
        assert diagnostics["attributes"]["SAT"] == "<REDACTED>"
        assert diagnostics["users"] == ["<REDACTED>"]

    def test_keeps_allowed_fields(self, wifi_lock: Lock) -> None:
        diagnostics = wifi_lock.get_diagnostics()
        assert diagnostics["name"] == "Door Lock"
        assert diagnostics["attributes"]["batteryLevel"] == 95


class TestImmutability:
    def test_cannot_assign(self, wifi_lock: Lock) -> None:
        with pytest.raises(AttributeError):
            wifi_lock.name = "nope"  # type: ignore[misc]

    def test_equality_ignores_raw_json(self, wifi_lock_json: dict[str, Any]) -> None:
        one = Lock.from_json(wifi_lock_json)
        two = Lock.from_json({**wifi_lock_json, "extraField": "ignored"})
        assert one == two
