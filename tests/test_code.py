from copy import deepcopy
from datetime import datetime
from typing import Any
from unittest.mock import Mock, call, create_autospec

import pytest

from pyschlage.code import AccessCode, DaysOfWeek, RecurringSchedule, TemporarySchedule
from pyschlage.device import Device
from pyschlage.exceptions import NotAuthenticatedError
from pyschlage.notification import Notification


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
