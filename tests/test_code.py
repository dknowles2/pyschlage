from copy import deepcopy
from datetime import datetime
from typing import Any
from unittest.mock import Mock, create_autospec, patch

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
            name="Friendly name",
            code="0123",
            schedule=None,
            device_id=wifi_device.device_id,
            access_code_id=access_code_id,
        )
        assert AccessCode.from_json(mock_auth, wifi_device, access_code_json) == code
        assert code.to_json() == access_code_json

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
            name="Friendly name",
            code="0123",
            schedule=sched,
            device_id=wifi_device.device_id,
            access_code_id=access_code_id,
        )
        assert AccessCode.from_json(mock_auth, wifi_device, json) == code
        assert code.to_json() == json

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
            name="Friendly name",
            code="0123",
            schedule=sched,
            device_id=wifi_device.device_id,
            access_code_id=access_code_id,
        )
        assert AccessCode.from_json(mock_auth, wifi_device, json) == code
        assert code.to_json() == json

    def test_save(
        self,
        mock_auth: Mock,
        access_code_json: dict[str, Any],
    ):
        with pytest.raises(NotAuthenticatedError):
            AccessCode().save()
        mock_device = create_autospec(Device, spec_set=True, device_id="__wifi_uuid__")
        code = AccessCode.from_json(mock_auth, mock_device, access_code_json)
        code.code = "1122"
        old_json = code.to_json()

        new_json = {"accesscodeId": "2211"}

        with patch(
            "pyschlage.code.Notification", autospec=True
        ) as mock_notification_cls:
            mock_notification = create_autospec(Notification, spec_set=True)
            mock_notification_cls.return_value = mock_notification
            mock_device.send_command.return_value = Mock(
                json=Mock(return_value=new_json)
            )
            code.save()
            mock_notification.save.assert_called_once_with()
            mock_device.send_command.assert_called_once_with(
                "updateaccesscode", old_json
            )
        assert code.code == "1122"
        assert code.access_code_id == "2211"

    def test_delete(self, mock_auth: Mock, access_code_json: dict[str, Any]):
        with pytest.raises(NotAuthenticatedError):
            AccessCode().delete()
        mock_device = create_autospec(Device, spec_set=True, device_id="__wifi_uuid__")
        code = AccessCode.from_json(mock_auth, mock_device, access_code_json)
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
