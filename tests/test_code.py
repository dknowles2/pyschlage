from copy import deepcopy
from datetime import UTC, datetime, timedelta, timezone, tzinfo
import time
from typing import Any
from unittest.mock import Mock, call, create_autospec
from zoneinfo import ZoneInfo

import pytest

from pyschlage.code import (
    AccessCode,
    DaysOfWeek,
    MultiRecurringSchedule,
    RecurringSchedule,
    TemporarySchedule,
)
from pyschlage.device import Device
from pyschlage.exceptions import InvalidCodeError, NotAuthenticatedError
from pyschlage.notification import Notification


class TestMultiRecurringSchedule:
    def test_schedule2_without_schedule1_raises(self):
        sched2 = RecurringSchedule(days_of_week=DaysOfWeek(mon=False))
        with pytest.raises(ValueError):
            MultiRecurringSchedule(None, sched2)

    def test_schedule1_only_is_valid(self):
        sched1 = RecurringSchedule(days_of_week=DaysOfWeek(mon=False))
        sched = MultiRecurringSchedule(sched1, None)
        assert sched.schedule1 == sched1
        assert sched.schedule2 is None


class TestAccessCode:
    def test_to_from_json(
        self, mock_auth: Mock, access_code_json: dict[str, Any], wifi_device: Device
    ):
        access_code_id = "__access_code_uuid__"
        code = AccessCode(
            _auth=mock_auth,
            _device=wifi_device,
            _json=access_code_json,
            name="Access code name",
            code="0123",
            schedule=None,
            device_id=wifi_device.device_id,
            access_code_id=access_code_id,
        )
        assert AccessCode.from_json(mock_auth, access_code_json, wifi_device) == code
        to_json = code.to_json()
        # Access codes returned by the API don't have the `notificationEnabled`` property, but
        # we need to pass it when saving an access code.
        assert to_json.pop("notificationEnabled") == 0
        # We also don't pass the `notification` property when saving an access code, but
        # it appears to always be 0 when returned by the API.
        access_code_json.pop("notification")
        assert to_json == access_code_json

    def test_to_from_json_multi_schedule(
        self, mock_auth: Mock, access_code_json: dict[str, Any], wifi_device: Device
    ):
        access_code_id = "__access_code_uuid__"
        sched1 = RecurringSchedule(days_of_week=DaysOfWeek(mon=False))
        sched2 = RecurringSchedule(days_of_week=DaysOfWeek(tue=False))
        sched = MultiRecurringSchedule(sched1, sched2)
        json = deepcopy(access_code_json)
        json["schedule1"] = sched1.to_json()
        json["schedule2"] = sched2.to_json()
        code = AccessCode(
            _auth=mock_auth,
            _json=json,
            _device=wifi_device,
            name="Access code name",
            code="0123",
            schedule=sched,
            device_id=wifi_device.device_id,
            access_code_id=access_code_id,
        )
        assert AccessCode.from_json(mock_auth, json, wifi_device) == code
        to_json = code.to_json()
        # Access codes returned by the API don't have the `notificationEnabled`` property, but
        # we need to pass it when saving an access code.
        assert to_json.pop("notificationEnabled") == 0
        # We also don't pass the `notification` property when saving an access code, but
        # it appears to always be 0 when returned by the API.
        json.pop("notification")
        assert to_json == json

    def test_to_from_json_recurring_schedule(
        self, mock_auth: Mock, access_code_json: dict[str, Any], wifi_device: Device
    ):
        assert RecurringSchedule.from_json({}) is None
        assert RecurringSchedule.from_json(None) is None
        access_code_id = "__access_code_uuid__"
        sched = RecurringSchedule(days_of_week=DaysOfWeek(mon=False))
        json = deepcopy(access_code_json)
        json["schedule1"] = sched.to_json()
        code = AccessCode(
            _auth=mock_auth,
            _json=json,
            _device=wifi_device,
            name="Access code name",
            code="0123",
            schedule=sched,
            device_id=wifi_device.device_id,
            access_code_id=access_code_id,
        )
        assert AccessCode.from_json(mock_auth, json, wifi_device) == code
        to_json = code.to_json()
        # Access codes returned by the API don't have the `notificationEnabled`` property, but
        # we need to pass it when saving an access code.
        assert to_json.pop("notificationEnabled") == 0
        # We also don't pass the `notification` property when saving an access code, but
        # it appears to always be 0 when returned by the API.
        json.pop("notification")
        assert to_json == json

    def test_to_from_json_temporary_schedule(
        self, mock_auth: Mock, access_code_json: dict[str, Any], wifi_device: Device
    ):
        access_code_id = "__access_code_uuid__"
        sched = TemporarySchedule(
            start=datetime(2022, 12, 25, 8, 30, 0),
            end=datetime(2022, 12, 25, 9, 0, 0),
        )
        json = deepcopy(access_code_json)
        json["activationSecs"] = 1671957000
        json["expirationSecs"] = 1671958800
        code = AccessCode(
            _auth=mock_auth,
            _json=json,
            _device=wifi_device,
            name="Access code name",
            code="0123",
            schedule=sched,
            device_id=wifi_device.device_id,
            access_code_id=access_code_id,
        )
        assert AccessCode.from_json(mock_auth, json, wifi_device) == code
        to_json = code.to_json()
        # Access codes returned by the API don't have the `notificationEnabled`` property, but
        # we need to pass it when saving an access code.
        assert to_json.pop("notificationEnabled") == 0
        # We also don't pass the `notification` property when saving an access code, but
        # it appears to always be 0 when returned by the API.
        json.pop("notification")
        assert to_json == json

    @pytest.mark.parametrize("code", ["", "7", "007", "123456789"])
    def test_save_rejects_wrong_length(
        self, mock_auth: Mock, access_code: AccessCode, code: str
    ):
        access_code.code = code
        with pytest.raises(InvalidCodeError, match="4 to 8 digits long"):
            access_code.save()
        mock_auth.request.assert_not_called()

    @pytest.mark.parametrize(
        "code", ["12a4", "1 23", "12.4", "+123", "\uff11\uff12\uff13\uff14"]
    )
    def test_save_rejects_non_digits(
        self, mock_auth: Mock, access_code: AccessCode, code: str
    ):
        access_code.code = code
        with pytest.raises(InvalidCodeError, match="only the digits") as exc_info:
            access_code.save()
        # Previously a non-numeric code raised a bare ValueError from save().
        assert isinstance(exc_info.value, ValueError)
        mock_auth.request.assert_not_called()

    @pytest.mark.parametrize(
        ("code", "want_code", "want_length"),
        [("0007", 7, 4), ("1234", 1234, 4), ("00000012", 12, 8)],
    )
    def test_to_json_keeps_leading_zeros(
        self, code: str, want_code: int, want_length: int
    ):
        json = AccessCode(code=code).to_json()
        assert json["accessCode"] == want_code
        assert json["accessCodeLength"] == want_length

    def test_save(
        self,
        mock_auth: Mock,
        access_code: AccessCode,
        notification_json: dict[str, Any],
    ):
        with pytest.raises(NotAuthenticatedError):
            AccessCode().save()
        access_code.access_code_id = None
        notification_json["active"] = False
        mock_auth.request.side_effect = [
            Mock(json=Mock(return_value={"accesscodeId": "__access_code_uuid__"})),
            Mock(json=Mock(return_value=notification_json)),
        ]
        access_code.save()
        mock_auth.request.assert_has_calls(
            [
                call(
                    "post",
                    "devices/__wifi_uuid__/commands",
                    json={
                        "data": {
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
                        },
                        "name": "addaccesscode",
                    },
                ),
                call(
                    "post",
                    "notifications",
                    params={"deviceId": "__wifi_uuid__"},
                    json={
                        "notificationId": "<user-id>___access_code_uuid__",
                        "devicetypeId": "be489wifi",
                        "notificationDefinitionId": "onunlockstateaction",
                        "active": False,
                        "filterValue": "Access code name",
                    },
                ),
            ]
        )
        assert not access_code.notify_on_use
        assert access_code._notification is not None
        assert not access_code._notification.active

    def test_save_new_with_notification(
        self,
        mock_auth: Mock,
        access_code: AccessCode,
        notification_json: dict[str, Any],
    ):
        access_code.access_code_id = None
        access_code.notify_on_use = True
        mock_auth.request.side_effect = [
            Mock(json=Mock(return_value={"accesscodeId": "2211"})),
            Mock(json=Mock(return_value=notification_json)),
        ]
        access_code.save()
        mock_auth.request.assert_has_calls(
            [
                call(
                    "post",
                    "devices/__wifi_uuid__/commands",
                    json={
                        "data": {
                            "friendlyName": "Access code name",
                            "accessCode": 123,
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
                        },
                        "name": "addaccesscode",
                    },
                ),
                call(
                    "post",
                    "notifications",
                    params={"deviceId": "__wifi_uuid__"},
                    json={
                        "notificationId": "<user-id>_2211",
                        "devicetypeId": "be489wifi",
                        "notificationDefinitionId": "onunlockstateaction",
                        "active": True,
                        "filterValue": "Access code name",
                    },
                ),
            ]
        )
        assert access_code.code == "0123"
        assert access_code.access_code_id == "2211"
        assert access_code.notify_on_use

    def test_save_disable_notification(
        self,
        mock_auth: Mock,
        wifi_device: Device,
        access_code: AccessCode,
        notification: Notification,
        notification_json: dict[str, Any],
    ):
        access_code.notify_on_use = False
        access_code._notification = notification
        notification.device_type = wifi_device.device_type
        notification_json["active"] = False
        mock_auth.request.side_effect = [
            Mock(json=Mock(return_value={"accesscodeId": "__access_code_uuid__"})),
            Mock(json=Mock(return_value=notification_json)),
        ]
        access_code.save()
        mock_auth.request.assert_has_calls(
            [
                call(
                    "post",
                    "devices/__wifi_uuid__/commands",
                    json={
                        "data": {
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
                        },
                        "name": "updateaccesscode",
                    },
                ),
                call(
                    "put",
                    "notifications/<user-id>___access_code_uuid__",
                    json={
                        "notificationId": "<user-id>___access_code_uuid__",
                        "devicetypeId": "be489wifi",
                        "notificationDefinitionId": "onunlockstateaction",
                        "active": False,
                        "filterValue": "Access code name",
                    },
                ),
            ]
        )
        assert not access_code.notify_on_use
        assert not notification.active

    def test_delete(self, mock_auth: Mock, access_code_json: dict[str, Any]):
        with pytest.raises(NotAuthenticatedError):
            AccessCode().delete()
        mock_device = create_autospec(Device, spec_set=True, device_id="__wifi_uuid__")
        code = AccessCode.from_json(mock_auth, access_code_json, mock_device)
        mock_notification = create_autospec(Notification, spec_set=True)
        code._notification = mock_notification
        mock_auth.request.return_value = Mock()
        json = code.to_json()
        code.delete()
        mock_device.send_command.assert_called_once_with("deleteaccesscode", json)
        mock_notification.delete.assert_called_once_with()
        assert code._auth is None
        assert code._json == {}
        assert code.access_code_id is None
        assert code.disabled


class TestDaysOfWeek:
    def test_to_str_all_days(self) -> None:
        assert DaysOfWeek().to_str() == "7F"

    def test_to_str_no_days(self) -> None:
        assert DaysOfWeek(*(False,) * 7).to_str() == "0"

    def test_to_str_single_day(self) -> None:
        assert DaysOfWeek(*(False,) * 6, sat=True).to_str() == "1"

    def test_from_str_round_trip(self) -> None:
        for want in ("0", "1", "7F", "40", "2A"):
            assert DaysOfWeek.from_str(want).to_str() == want


class _NullOffsetTz(tzinfo):
    def utcoffset(self, dt: datetime | None) -> timedelta | None:
        return None

    def dst(self, dt: datetime | None) -> timedelta | None:
        return None

    def tzname(self, dt: datetime | None) -> str | None:
        return "NULL"


class TestTemporarySchedule:
    def test_rejects_aware_datetimes(self) -> None:
        naive = datetime(2026, 11, 16, 13, 0, 0)
        aware = datetime(2026, 11, 16, 13, 0, 0, tzinfo=UTC)
        with pytest.raises(ValueError, match="naive lock-local"):
            TemporarySchedule(start=aware, end=naive)
        with pytest.raises(ValueError, match="naive lock-local"):
            TemporarySchedule(start=naive, end=aware)

    def test_rejects_post_init_aware_mutation(self) -> None:
        ny = ZoneInfo("America/New_York")
        sched = TemporarySchedule(
            start=datetime(2026, 11, 16, 13, 0, 0),
            end=datetime(2026, 11, 16, 13, 10, 0),
        )
        sched.start = datetime(2026, 11, 16, 18, 0, 0, tzinfo=UTC)
        with pytest.raises(ValueError, match="naive lock-local"):
            sched.to_json()
        with pytest.raises(ValueError, match="naive lock-local"):
            sched.to_aware(ny)

    def test_app_reference_est_read_and_write(self) -> None:
        # Reference fixture from #607: Schlage app schedule for
        # 2026-11-16 13:00-13:10 America/New_York (EST, UTC-5).
        ny = ZoneInfo("America/New_York")
        wire = {"activationSecs": 1794834000, "expirationSecs": 1794834600}

        # Read path: wire -> naive wall-clock -> aware instants
        sched = TemporarySchedule.from_json(wire)
        assert sched == TemporarySchedule(
            start=datetime(2026, 11, 16, 13, 0, 0),
            end=datetime(2026, 11, 16, 13, 10, 0),
        )
        start_aware, end_aware = sched.to_aware(ny)
        assert start_aware == datetime(2026, 11, 16, 18, 0, 0, tzinfo=UTC)
        assert end_aware == datetime(2026, 11, 16, 18, 10, 0, tzinfo=UTC)

        # Write path: UTC instants -> TemporarySchedule -> wire
        written = TemporarySchedule.from_aware(
            datetime(2026, 11, 16, 18, 0, 0, tzinfo=UTC),
            datetime(2026, 11, 16, 18, 10, 0, tzinfo=UTC),
            ny,
        )
        assert written == sched
        assert written.to_json() == wire

    def test_app_reference_pst_read_and_write(self) -> None:
        # Reference fixture from #355: Schlage app schedule starting
        # 2026-02-15 15:36 America/Los_Angeles (PST, UTC-8).
        la = ZoneInfo("America/Los_Angeles")
        wire = {"activationSecs": 1771169760, "expirationSecs": 1771173360}

        sched = TemporarySchedule.from_json(wire)
        assert sched.start == datetime(2026, 2, 15, 15, 36, 0)
        start_aware, end_aware = sched.to_aware(la)
        assert start_aware == datetime(2026, 2, 15, 23, 36, 0, tzinfo=UTC)
        assert end_aware == datetime(2026, 2, 16, 0, 36, 0, tzinfo=UTC)

        written = TemporarySchedule.from_aware(start_aware, end_aware, la)
        assert written.to_json() == wire

    @pytest.mark.parametrize(
        ("zone_name", "utc_start", "utc_end", "want_wall_start", "want_wall_end"),
        [
            # Standard time (EST, UTC-5)
            (
                "America/New_York",
                datetime(2027, 1, 15, 18, 0, 0, tzinfo=UTC),
                datetime(2027, 1, 15, 18, 10, 0, tzinfo=UTC),
                datetime(2027, 1, 15, 13, 0, 0),
                datetime(2027, 1, 15, 13, 10, 0),
            ),
            # Daylight saving time (EDT, UTC-4)
            (
                "America/New_York",
                datetime(2027, 7, 15, 17, 0, 0, tzinfo=UTC),
                datetime(2027, 7, 15, 17, 10, 0, tzinfo=UTC),
                datetime(2027, 7, 15, 13, 0, 0),
                datetime(2027, 7, 15, 13, 10, 0),
            ),
            # Stay straddling spring-forward transition (EST -> EDT)
            (
                "America/New_York",
                datetime(2026, 3, 7, 20, 0, 0, tzinfo=UTC),
                datetime(2026, 3, 9, 15, 0, 0, tzinfo=UTC),
                datetime(2026, 3, 7, 15, 0, 0),
                datetime(2026, 3, 9, 11, 0, 0),
            ),
            # Stay straddling fall-back transition (EDT -> EST)
            (
                "America/New_York",
                datetime(2026, 10, 31, 19, 0, 0, tzinfo=UTC),
                datetime(2026, 11, 2, 16, 0, 0, tzinfo=UTC),
                datetime(2026, 10, 31, 15, 0, 0),
                datetime(2026, 11, 2, 11, 0, 0),
            ),
            # Negative DST (Europe/Dublin: IST UTC+1 summer -> GMT UTC+0 winter)
            (
                "Europe/Dublin",
                datetime(2026, 10, 24, 12, 0, 0, tzinfo=UTC),
                datetime(2026, 10, 26, 12, 0, 0, tzinfo=UTC),
                datetime(2026, 10, 24, 13, 0, 0),
                datetime(2026, 10, 26, 12, 0, 0),
            ),
            # Southern hemisphere DST (Australia/Sydney: AEDT UTC+11 -> AEST UTC+10)
            (
                "Australia/Sydney",
                datetime(2026, 4, 4, 12, 0, 0, tzinfo=UTC),
                datetime(2026, 4, 6, 12, 0, 0, tzinfo=UTC),
                datetime(2026, 4, 4, 23, 0, 0),
                datetime(2026, 4, 6, 22, 0, 0),
            ),
        ],
    )
    def test_dst_and_transitions(
        self,
        zone_name: str,
        utc_start: datetime,
        utc_end: datetime,
        want_wall_start: datetime,
        want_wall_end: datetime,
    ) -> None:
        tz = ZoneInfo(zone_name)
        sched = TemporarySchedule.from_aware(utc_start, utc_end, tz)
        assert sched.start == want_wall_start
        assert sched.end == want_wall_end

        round_tripped = TemporarySchedule.from_json(sched.to_json())
        assert round_tripped == sched
        got_start, got_end = round_tripped.to_aware(tz)
        assert got_start == utc_start
        assert got_end == utc_end

    def test_from_aware_accepts_different_input_timezones(self) -> None:
        ny = ZoneInfo("America/New_York")
        la = ZoneInfo("America/Los_Angeles")
        fixed_minus_5 = timezone(timedelta(hours=-5))

        sched = TemporarySchedule.from_aware(
            datetime(2026, 11, 16, 10, 0, 0, tzinfo=la),
            datetime(2026, 11, 16, 13, 10, 0, tzinfo=fixed_minus_5),
            ny,
        )
        assert sched == TemporarySchedule(
            start=datetime(2026, 11, 16, 13, 0, 0),
            end=datetime(2026, 11, 16, 13, 10, 0),
        )

    def test_to_json_floors_subsecond_timestamps(self) -> None:
        # Exact integer flooring avoids float truncation toward zero
        # (1969-12-31 23:59:59.5 -> -1, not 0).
        sched = TemporarySchedule(
            start=datetime(1969, 12, 31, 23, 59, 59, 500000),
            end=datetime(2026, 11, 16, 13, 0, 0, 999999),
        )
        assert sched.to_json() == {
            "activationSecs": -1,
            "expirationSecs": 1794834000,
        }

    @pytest.mark.skipif(not hasattr(time, "tzset"), reason="time.tzset() is Unix-only")
    @pytest.mark.parametrize("host_tz", ["Asia/Tokyo", "America/Los_Angeles"])
    def test_host_timezone_independence(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_auth: Mock,
        access_code_json: dict[str, Any],
        wifi_device: Device,
        host_tz: str,
    ) -> None:
        # Lock is in America/New_York while host TZ differs.
        ny = ZoneInfo("America/New_York")
        wire = {"activationSecs": 1794834000, "expirationSecs": 1794834600}
        code_json = deepcopy(access_code_json)
        code_json.update(wire)

        monkeypatch.setenv("TZ", host_tz)
        time.tzset()
        try:
            sched = TemporarySchedule.from_aware(
                datetime(2026, 11, 16, 18, 0, 0, tzinfo=UTC),
                datetime(2026, 11, 16, 18, 10, 0, tzinfo=UTC),
                ny,
            )
            assert sched == TemporarySchedule(
                start=datetime(2026, 11, 16, 13, 0, 0),
                end=datetime(2026, 11, 16, 13, 10, 0),
            )
            assert sched.to_json() == wire
            assert sched.to_aware(ny) == (
                datetime(2026, 11, 16, 18, 0, 0, tzinfo=UTC),
                datetime(2026, 11, 16, 18, 10, 0, tzinfo=UTC),
            )

            code = AccessCode.from_json(mock_auth, code_json, wifi_device)
            assert code.schedule == sched
            to_json = code.to_json()
            assert to_json["activationSecs"] == wire["activationSecs"]
            assert to_json["expirationSecs"] == wire["expirationSecs"]
        finally:
            monkeypatch.delenv("TZ", raising=False)
            time.tzset()

    def test_access_code_save_with_temporary_schedule(
        self,
        mock_auth: Mock,
        access_code: AccessCode,
        notification_json: dict[str, Any],
    ) -> None:
        ny = ZoneInfo("America/New_York")
        access_code.access_code_id = None
        access_code.schedule = TemporarySchedule.from_aware(
            datetime(2026, 11, 16, 18, 0, 0, tzinfo=UTC),
            datetime(2026, 11, 16, 18, 10, 0, tzinfo=UTC),
            ny,
        )
        notification_json["active"] = False
        mock_auth.request.side_effect = [
            Mock(json=Mock(return_value={"accesscodeId": "__access_code_uuid__"})),
            Mock(json=Mock(return_value=notification_json)),
        ]
        access_code.save()
        sent_data = mock_auth.request.call_args_list[0].kwargs["json"]["data"]
        assert sent_data["activationSecs"] == 1794834000
        assert sent_data["expirationSecs"] == 1794834600

    def test_access_code_asymmetric_sentinels(
        self, mock_auth: Mock, access_code_json: dict[str, Any], wifi_device: Device
    ) -> None:
        # Only activationSecs is 0 (no start) with a real expirationSecs.
        no_start = deepcopy(access_code_json)
        no_start["expirationSecs"] = 1794834600
        code1 = AccessCode.from_json(mock_auth, no_start, wifi_device)
        assert code1.schedule == TemporarySchedule(
            start=datetime(1970, 1, 1, 0, 0, 0),
            end=datetime(2026, 11, 16, 13, 10, 0),
        )

        # Real activationSecs with expirationSecs == 0xFFFFFFFF (no end).
        no_end = deepcopy(access_code_json)
        no_end["activationSecs"] = 1794834000
        code2 = AccessCode.from_json(mock_auth, no_end, wifi_device)
        assert code2.schedule == TemporarySchedule(
            start=datetime(2026, 11, 16, 13, 0, 0),
            end=datetime(2106, 2, 7, 6, 28, 15),
        )

    def test_rejects_invalid_tzinfo(self) -> None:
        aware = datetime(2026, 11, 16, 18, 0, 0, tzinfo=UTC)
        sched = TemporarySchedule(
            start=datetime(2026, 11, 16, 13, 0, 0),
            end=datetime(2026, 11, 16, 13, 10, 0),
        )
        with pytest.raises(TypeError, match="datetime.tzinfo"):
            TemporarySchedule.from_aware(aware, aware, None)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="datetime.tzinfo"):
            sched.to_aware(None)  # type: ignore[arg-type]

        null_tz = _NullOffsetTz()
        with pytest.raises(ValueError, match="no UTC offset"):
            sched.to_aware(null_tz)

    def test_from_aware_rejects_naive_input(self) -> None:
        ny = ZoneInfo("America/New_York")
        naive = datetime(2026, 11, 16, 13, 0, 0)
        null_offset_dt = datetime(2026, 11, 16, 13, 0, 0, tzinfo=_NullOffsetTz())
        aware = datetime(2026, 11, 16, 18, 0, 0, tzinfo=UTC)
        with pytest.raises(ValueError, match="timezone-aware"):
            TemporarySchedule.from_aware(naive, aware, ny)
        with pytest.raises(ValueError, match="timezone-aware"):
            TemporarySchedule.from_aware(aware, naive, ny)
        with pytest.raises(ValueError, match="timezone-aware"):
            TemporarySchedule.from_aware(null_offset_dt, aware, ny)

    def test_from_aware_rejects_dst_gap(self) -> None:
        ny = ZoneInfo("America/New_York")
        # 2026-03-08 02:30 does not exist in America/New_York (spring forward).
        nonexistent = datetime(2026, 3, 8, 2, 30, 0, tzinfo=ny)
        valid_before = datetime(2026, 3, 8, 1, 0, 0, tzinfo=ny)
        valid_after = datetime(2026, 3, 8, 4, 0, 0, tzinfo=ny)
        with pytest.raises(ValueError, match="does not exist"):
            TemporarySchedule.from_aware(nonexistent, valid_after, ny)
        with pytest.raises(ValueError, match="does not exist"):
            TemporarySchedule.from_aware(valid_before, nonexistent, ny)

    @pytest.mark.parametrize(
        "ambiguous_utc",
        [
            datetime(2026, 11, 1, 5, 30, 0, tzinfo=UTC),  # 01:30 EDT (fold=0)
            datetime(2026, 11, 1, 6, 30, 0, tzinfo=UTC),  # 01:30 EST (fold=1)
        ],
    )
    def test_from_aware_rejects_ambiguous_dst_fold(
        self, ambiguous_utc: datetime
    ) -> None:
        ny = ZoneInfo("America/New_York")
        valid_start = datetime(2026, 11, 1, 4, 0, 0, tzinfo=UTC)
        valid_end = datetime(2026, 11, 1, 10, 0, 0, tzinfo=UTC)
        with pytest.raises(ValueError, match="ambiguous"):
            TemporarySchedule.from_aware(ambiguous_utc, valid_end, ny)
        with pytest.raises(ValueError, match="ambiguous"):
            TemporarySchedule.from_aware(valid_start, ambiguous_utc, ny)

    def test_to_aware_dst_fold_and_gap(self) -> None:
        ny = ZoneInfo("America/New_York")

        # Repeated hour on fall-back day: fold=0 (EDT) vs fold=1 (EST).
        fold_sched = TemporarySchedule(
            start=datetime(2026, 11, 1, 1, 30, 0),
            end=datetime(2026, 11, 1, 1, 45, 0),
        )
        start0, end0 = fold_sched.to_aware(ny)
        assert start0.fold == 0
        assert start0.utcoffset() == timedelta(hours=-4)
        assert start0.astimezone(UTC) == datetime(2026, 11, 1, 5, 30, 0, tzinfo=UTC)
        assert end0.astimezone(UTC) == datetime(2026, 11, 1, 5, 45, 0, tzinfo=UTC)

        start1, end1 = fold_sched.to_aware(ny, fold=1)
        assert start1.fold == 1
        assert start1.utcoffset() == timedelta(hours=-5)
        assert start1.astimezone(UTC) == datetime(2026, 11, 1, 6, 30, 0, tzinfo=UTC)
        assert end1.astimezone(UTC) == datetime(2026, 11, 1, 6, 45, 0, tzinfo=UTC)

        # Per-endpoint fold tuple spanning EDT -> EST (01:45 EDT -> 01:15 EST).
        spanning_fold = TemporarySchedule(
            start=datetime(2026, 11, 1, 1, 45, 0),
            end=datetime(2026, 11, 1, 1, 15, 0),
        )
        span_start, span_end = spanning_fold.to_aware(ny, fold=(0, 1))
        assert span_start.astimezone(UTC) == datetime(2026, 11, 1, 5, 45, 0, tzinfo=UTC)
        assert span_end.astimezone(UTC) == datetime(2026, 11, 1, 6, 15, 0, tzinfo=UTC)
        assert span_start.astimezone(UTC) < span_end.astimezone(UTC)

        # Unambiguous endpoints are normalized to fold=0 even when fold=1 is passed.
        unambiguous = TemporarySchedule(
            start=datetime(2026, 11, 1, 0, 30, 0),
            end=datetime(2026, 11, 1, 1, 30, 0),
        )
        norm_start, norm_end = unambiguous.to_aware(ny, fold=1)
        assert norm_start.fold == 0
        assert norm_end.fold == 1

        # Invalid fold values (out-of-range, bool, float, bad tuple length).
        for bad_fold in (2, True, False, 1.0, (0,)):
            with pytest.raises(ValueError, match="fold"):
                fold_sched.to_aware(ny, fold=bad_fold)  # type: ignore[arg-type]

        # Nonexistent hour on spring-forward day raises ValueError (start and end).
        gap_start = TemporarySchedule(
            start=datetime(2026, 3, 8, 2, 30, 0),
            end=datetime(2026, 3, 8, 4, 0, 0),
        )
        with pytest.raises(ValueError, match="does not exist"):
            gap_start.to_aware(ny)

        gap_end = TemporarySchedule(
            start=datetime(2026, 3, 8, 1, 0, 0),
            end=datetime(2026, 3, 8, 2, 30, 0),
        )
        with pytest.raises(ValueError, match="does not exist"):
            gap_end.to_aware(ny)
