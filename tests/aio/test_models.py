"""Tests for the immutable snapshot models."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from typing import Any

import pytest

from pyschlage.aio.code import AccessCode, NewAccessCode
from pyschlage.aio.lock import Lock
from pyschlage.aio.notification import Notification
from pyschlage.code import DaysOfWeek, RecurringSchedule, TemporarySchedule
from pyschlage.log import KEYPAD_DISABLED_INVALID_CODE, LockLog
from pyschlage.notification import ON_UNLOCK_ACTION


class TestLock:
    def test_from_json(self, wifi_lock_json: dict[str, Any]) -> None:
        lock = Lock.from_json(wifi_lock_json)
        assert lock.device_id == "__wifi_uuid__"
        assert lock.device_type == "be489wifi"
        assert lock.name == "Door Lock"
        assert lock.model_name == "__model_name__"
        assert lock.battery_level == 95
        assert lock.is_locked
        assert not lock.is_jammed
        assert lock.beeper_enabled
        assert lock.lock_and_leave_enabled
        assert lock.mac_address == "AA:BB:CC:00:11:22"
        assert set(lock.users) == {"user-uuid", "foo-bar-uuid"}

    def test_is_immutable(self, wifi_lock_json: dict[str, Any]) -> None:
        lock = Lock.from_json(wifi_lock_json)
        with pytest.raises(FrozenInstanceError):
            lock.is_locked = False  # type: ignore[misc]

    def test_compares_on_state(self, wifi_lock_json: dict[str, Any]) -> None:
        lock = Lock.from_json(wifi_lock_json)
        assert lock == Lock.from_json(wifi_lock_json)
        assert lock != replace(lock, is_locked=False)

    def test_raw_json_is_not_compared(self, wifi_lock_json: dict[str, Any]) -> None:
        # Two snapshots describing the same state are equal even when the
        # payloads they came from differ, so consumers can skip redundant work.
        lock = Lock.from_json(wifi_lock_json)
        other_json = dict(wifi_lock_json, lastUpdated="2024-01-01T00:00:00.000Z")
        assert lock == Lock.from_json(other_json)

    def test_is_wifi_lock(
        self, wifi_lock_json: dict[str, Any], ble_lock_json: dict[str, Any]
    ) -> None:
        assert Lock.from_json(wifi_lock_json).is_wifi_lock
        assert not Lock.from_json(ble_lock_json).is_wifi_lock

    def test_unavailable_lock(self, wifi_lock_unavailable_json: dict[str, Any]) -> None:
        lock = Lock.from_json(wifi_lock_unavailable_json)
        assert lock.is_locked is None
        assert lock.is_jammed is None
        assert lock.battery_level is None
        assert lock.firmware_version is None

    def test_get_diagnostics(self, wifi_lock_json: dict[str, Any]) -> None:
        diagnostics = Lock.from_json(wifi_lock_json).get_diagnostics()
        assert diagnostics["name"] == "Door Lock"
        assert diagnostics["deviceId"] == "<REDACTED>"

    def test_last_changed_by(self, wifi_lock_json: dict[str, Any]) -> None:
        wifi_lock_json["attributes"]["lockStateMetadata"] = {
            "actionType": "thumbTurn",
            "UUID": None,
            "name": None,
        }
        assert Lock.from_json(wifi_lock_json).last_changed_by() == "thumbturn"

    def test_last_changed_by_without_metadata(
        self, wifi_lock_json: dict[str, Any]
    ) -> None:
        del wifi_lock_json["attributes"]["lockStateMetadata"]
        assert Lock.from_json(wifi_lock_json).last_changed_by() is None

    def test_keypad_disabled(self, lock_log: LockLog) -> None:
        assert not Lock.keypad_disabled([])
        assert not Lock.keypad_disabled([lock_log])
        disabled = replace(lock_log, event_code=KEYPAD_DISABLED_INVALID_CODE)
        assert Lock.keypad_disabled([disabled])


class TestNotification:
    def test_to_from_json(self, notification_json: dict[str, Any]) -> None:
        notification = Notification.from_json(notification_json)
        assert notification.notification_id == "<user-id>___access_code_uuid__"
        assert notification.user_id == "<user-id>"
        assert notification.device_id == "__wifi_uuid__"
        assert notification.notification_type == ON_UNLOCK_ACTION
        assert notification.active
        assert notification.filter_value == "Access code name"
        assert notification.created_at == datetime(
            2023, 3, 1, 17, 26, 47, 366000, tzinfo=UTC
        )
        assert notification.to_json() == {
            "notificationId": "<user-id>___access_code_uuid__",
            "devicetypeId": None,
            "notificationDefinitionId": ON_UNLOCK_ACTION,
            "active": True,
            "filterValue": "Access code name",
        }

    def test_to_json_without_filter_value(
        self, notification_json: dict[str, Any]
    ) -> None:
        del notification_json["filterValue"]
        assert "filterValue" not in Notification.from_json(notification_json).to_json()


class TestAccessCode:
    def test_from_json(self, access_code_json: dict[str, Any]) -> None:
        code = AccessCode.from_json(
            access_code_json, device_id="__wifi_uuid__", device_type="be489wifi"
        )
        assert code.access_code_id == "__access_code_uuid__"
        assert code.device_id == "__wifi_uuid__"
        assert code.device_type == "be489wifi"
        assert code.name == "Access code name"
        assert code.code == "0123"
        assert code.schedule is None
        assert not code.notify_on_use
        assert not code.disabled

    def test_notify_on_use_follows_the_notification(
        self, access_code_json: dict[str, Any], notification_json: dict[str, Any]
    ) -> None:
        notification = Notification.from_json(notification_json)
        code = AccessCode.from_json(
            access_code_json,
            device_id="__wifi_uuid__",
            device_type="be489wifi",
            notification=notification,
        )
        assert code.notify_on_use
        assert code._notification is notification

    def test_to_json_round_trip(self, access_code_json: dict[str, Any]) -> None:
        code = AccessCode.from_json(
            access_code_json, device_id="__wifi_uuid__", device_type="be489wifi"
        )
        assert code.to_json() == {
            "friendlyName": "Access code name",
            "accessCode": 123,
            "accessCodeLength": 4,
            "notificationEnabled": 0,
            "disabled": 0,
            "activationSecs": 0,
            "expirationSecs": 4294967295,
            "schedule1": {
                "daysOfWeek": "7F",
                "startHour": 0,
                "startMinute": 0,
                "endHour": 23,
                "endMinute": 59,
            },
            "accesscodeId": "__access_code_uuid__",
        }

    def test_recurring_schedule(self, access_code_json: dict[str, Any]) -> None:
        access_code_json["schedule1"]["daysOfWeek"] = "5F"
        code = AccessCode.from_json(
            access_code_json, device_id="__wifi_uuid__", device_type="be489wifi"
        )
        assert code.schedule == RecurringSchedule(
            days_of_week=DaysOfWeek.from_str("5F")
        )
        assert code.to_json()["schedule1"]["daysOfWeek"] == "5F"

    def test_temporary_schedule(self, access_code_json: dict[str, Any]) -> None:
        access_code_json["activationSecs"] = 1000
        access_code_json["expirationSecs"] = 2000
        code = AccessCode.from_json(
            access_code_json, device_id="__wifi_uuid__", device_type="be489wifi"
        )
        assert code.schedule == TemporarySchedule(
            start=datetime.fromtimestamp(1000, tz=UTC),
            end=datetime.fromtimestamp(2000, tz=UTC),
        )
        assert code.to_json()["activationSecs"] == 1000
        assert code.to_json()["expirationSecs"] == 2000

    def test_is_immutable(self, access_code_json: dict[str, Any]) -> None:
        code = AccessCode.from_json(
            access_code_json, device_id="__wifi_uuid__", device_type="be489wifi"
        )
        with pytest.raises(FrozenInstanceError):
            code.name = "nope"  # type: ignore[misc]
        assert replace(code, name="renamed").name == "renamed"


class TestNewAccessCode:
    def test_to_json(self) -> None:
        code = NewAccessCode(name="New code", code="1234", notify_on_use=True)
        assert code.to_json() == {
            "friendlyName": "New code",
            "accessCode": 1234,
            "accessCodeLength": 4,
            "notificationEnabled": 1,
            "disabled": 0,
            "activationSecs": 0,
            "expirationSecs": 4294967295,
            "schedule1": {
                "daysOfWeek": "7F",
                "startHour": 0,
                "startMinute": 0,
                "endHour": 23,
                "endMinute": 59,
            },
        }
        # A new code has no id yet, so none is sent.
        assert "accesscodeId" not in code.to_json()
