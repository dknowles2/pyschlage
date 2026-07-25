from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from pyschlage.code import (
    AccessCode,
    DaysOfWeek,
    MultiRecurringSchedule,
    NewAccessCode,
    RecurringSchedule,
    TemporarySchedule,
)
from pyschlage.notification import Notification

NO_DAYS = DaysOfWeek(
    sun=False, mon=False, tue=False, wed=False, thu=False, fri=False, sat=False
)
SAT_ONLY = DaysOfWeek(
    sun=False, mon=False, tue=False, wed=False, thu=False, fri=False, sat=True
)


class TestDaysOfWeek:
    def test_round_trip_all_days(self) -> None:
        assert DaysOfWeek().to_str() == "7F"
        assert DaysOfWeek.from_str("7F") == DaysOfWeek()

    def test_round_trip_no_days(self) -> None:
        assert NO_DAYS.to_str() == "00"
        assert DaysOfWeek.from_str("00") == NO_DAYS

    def test_round_trip_single_day(self) -> None:
        assert DaysOfWeek.from_str(SAT_ONLY.to_str()) == SAT_ONLY

    def test_to_str_is_always_two_digits(self) -> None:
        # int(s, 16) round-trips either way, but the service has only ever been
        # sent two hex digits.
        assert len(SAT_ONLY.to_str()) == 2


class TestRecurringSchedule:
    def test_from_json_none(self) -> None:
        assert RecurringSchedule.from_json(None) is None

    def test_from_json_whole_week_is_none(self) -> None:
        json = {
            "daysOfWeek": "7F",
            "startHour": 0,
            "startMinute": 0,
            "endHour": 23,
            "endMinute": 59,
        }
        assert RecurringSchedule.from_json(json) is None

    def test_from_json(self) -> None:
        json = {
            "daysOfWeek": "7F",
            "startHour": 8,
            "startMinute": 30,
            "endHour": 17,
            "endMinute": 0,
        }
        assert RecurringSchedule.from_json(json) == RecurringSchedule(
            DaysOfWeek(), 8, 30, 17, 0
        )

    def test_to_json(self) -> None:
        assert RecurringSchedule(DaysOfWeek(), 8, 30, 17, 0).to_json() == {
            "daysOfWeek": "7F",
            "startHour": 8,
            "startMinute": 30,
            "endHour": 17,
            "endMinute": 0,
        }


class TestMultiRecurringSchedule:
    def test_schedule2_requires_schedule1(self) -> None:
        with pytest.raises(ValueError, match="schedule1 must be set"):
            MultiRecurringSchedule(None, RecurringSchedule())

    def test_both_none_is_allowed(self) -> None:
        assert MultiRecurringSchedule(None, None).schedule1 is None


class TestTemporarySchedule:
    def test_round_trip(self) -> None:
        sched = TemporarySchedule(
            start=datetime(2023, 1, 1, tzinfo=UTC),
            end=datetime(2023, 1, 2, tzinfo=UTC),
        )
        assert TemporarySchedule.from_json(sched.to_json()) == sched


class TestNewAccessCode:
    def test_to_json(self) -> None:
        code = NewAccessCode(name="Guest", code="1234")
        assert code.to_json() == {
            "friendlyName": "Guest",
            "accessCode": 1234,
            "accessCodeLength": 4,
            "notificationEnabled": 0,
            "disabled": 0,
            "activationSecs": 0,
            "expirationSecs": 4294967295,
            "schedule1": RecurringSchedule().to_json(),
        }

    def test_to_json_no_access_code_id(self) -> None:
        assert "accesscodeId" not in NewAccessCode(name="Guest", code="1234").to_json()

    def test_to_json_recurring_schedule(self) -> None:
        sched = RecurringSchedule(DaysOfWeek(), 8, 30, 17, 0)
        code = NewAccessCode(name="Guest", code="1234", schedule=sched)
        assert code.to_json()["schedule1"] == sched.to_json()

    def test_to_json_temporary_schedule(self) -> None:
        sched = TemporarySchedule(
            start=datetime(2023, 1, 1, tzinfo=UTC),
            end=datetime(2023, 1, 2, tzinfo=UTC),
        )
        json = NewAccessCode(name="Guest", code="1234", schedule=sched).to_json()
        assert json["activationSecs"] == int(sched.start.timestamp())
        assert json["expirationSecs"] == int(sched.end.timestamp())

    def test_to_json_multi_recurring_schedule(self) -> None:
        one = RecurringSchedule(DaysOfWeek(), 8, 30, 17, 0)
        two = RecurringSchedule(DaysOfWeek(), 18, 0, 20, 0)
        json = NewAccessCode(
            name="Guest", code="1234", schedule=MultiRecurringSchedule(one, two)
        ).to_json()
        assert json["schedule1"] == one.to_json()
        assert json["schedule2"] == two.to_json()

    def test_to_json_multi_recurring_schedule_partial(self) -> None:
        json = NewAccessCode(
            name="Guest", code="1234", schedule=MultiRecurringSchedule(None, None)
        ).to_json()
        assert json["schedule1"] == RecurringSchedule().to_json()
        assert "schedule2" not in json

    def test_to_json_notify_and_disabled(self) -> None:
        json = NewAccessCode(
            name="Guest", code="1234", notify_on_use=True, disabled=True
        ).to_json()
        assert json["notificationEnabled"] == 1
        assert json["disabled"] == 1


class TestAccessCode:
    def test_request_path(self) -> None:
        assert AccessCode.request_path("dev") == "devices/dev/storage/accesscode"
        assert (
            AccessCode.request_path("dev", "code")
            == "devices/dev/storage/accesscode/code"
        )

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
        assert code.notify_on_use is False
        assert code.disabled is False

    def test_from_json_pads_to_code_length(
        self, access_code_json: dict[str, Any]
    ) -> None:
        access_code_json["accessCodeLength"] = 6
        code = AccessCode.from_json(access_code_json, device_id="d")
        assert code.code == "000123"

    def test_from_json_default_code_length(
        self, access_code_json: dict[str, Any]
    ) -> None:
        del access_code_json["accessCodeLength"]
        assert AccessCode.from_json(access_code_json, device_id="d").code == "0123"

    def test_from_json_temporary_schedule(
        self, access_code_json: dict[str, Any]
    ) -> None:
        access_code_json["activationSecs"] = 1672531200
        access_code_json["expirationSecs"] = 1672617600
        code = AccessCode.from_json(access_code_json, device_id="d")
        assert code.schedule == TemporarySchedule(
            start=datetime.fromtimestamp(1672531200, tz=UTC),
            end=datetime.fromtimestamp(1672617600, tz=UTC),
        )

    def test_from_json_multi_recurring_schedule(
        self, access_code_json: dict[str, Any]
    ) -> None:
        access_code_json["schedule1"] = {
            "daysOfWeek": "7F",
            "startHour": 8,
            "startMinute": 0,
            "endHour": 12,
            "endMinute": 0,
        }
        access_code_json["schedule2"] = {
            "daysOfWeek": "7F",
            "startHour": 13,
            "startMinute": 0,
            "endHour": 17,
            "endMinute": 0,
        }
        code = AccessCode.from_json(access_code_json, device_id="d")
        assert isinstance(code.schedule, MultiRecurringSchedule)
        assert code.schedule.schedule1 == RecurringSchedule(DaysOfWeek(), 8, 0, 12, 0)
        assert code.schedule.schedule2 == RecurringSchedule(DaysOfWeek(), 13, 0, 17, 0)

    def test_from_json_notify_on_use_from_notification(
        self, access_code_json: dict[str, Any], notification: Notification
    ) -> None:
        code = AccessCode.from_json(
            access_code_json, device_id="d", notification=notification
        )
        assert code.notify_on_use is True
        assert code._notification is notification

    def test_from_json_inactive_notification(
        self, access_code_json: dict[str, Any], notification: Notification
    ) -> None:
        code = AccessCode.from_json(
            access_code_json,
            device_id="d",
            notification=replace(notification, active=False),
        )
        assert code.notify_on_use is False

    def test_from_json_disabled(self, access_code_json: dict[str, Any]) -> None:
        access_code_json["disabled"] = 1
        assert AccessCode.from_json(access_code_json, device_id="d").disabled is True

    def test_to_json_includes_id(self, access_code: AccessCode) -> None:
        assert access_code.to_json()["accesscodeId"] == "__access_code_uuid__"

    def test_replace_produces_modified_copy(self, access_code: AccessCode) -> None:
        updated = replace(access_code, name="Renamed")
        assert updated.name == "Renamed"
        assert access_code.name == "Access code name"
        assert updated.access_code_id == access_code.access_code_id

    def test_is_immutable(self, access_code: AccessCode) -> None:
        with pytest.raises(AttributeError):
            access_code.name = "nope"  # type: ignore[misc]
