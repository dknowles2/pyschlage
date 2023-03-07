from copy import deepcopy
from datetime import datetime
from unittest import mock

import pyschlage
from pyschlage.auth import Auth
from pyschlage.code import AccessCode, DaysOfWeek, RecurringSchedule, TemporarySchedule


class TestAccessCode:
    def test_to_from_json(self, access_code_json):
        auth = mock.create_autospec(Auth, spec_set=True)
        device_id = "__device_uuid__"
        access_code_id = "__access_code_uuid__"
        code = AccessCode(
            _auth=auth,
            name="Friendly name",
            code="0123",
            schedule=None,
            device_id=device_id,
            access_code_id=access_code_id,
        )
        assert AccessCode.from_json(auth, access_code_json, device_id) == code

        want_json = deepcopy(access_code_json)
        # We don't send back the id because it's not mutable.
        del want_json["accesscodeId"]
        assert code.to_json() == want_json

    def test_to_from_json_recurring_schedule(self, access_code_json):
        auth = mock.create_autospec(Auth, spec_set=True)
        device_id = "__device_uuid__"
        access_code_id = "__access_code_uuid__"
        sched = RecurringSchedule(days_of_week=DaysOfWeek(mon=False))
        json = deepcopy(access_code_json)
        json["schedule1"] = sched.to_json()
        code = AccessCode(
            _auth=auth,
            name="Friendly name",
            code="0123",
            schedule=sched,
            device_id=device_id,
            access_code_id=access_code_id,
        )
        assert AccessCode.from_json(auth, json, device_id) == code

        # We don't send back the id because it's not mutable.
        del json["accesscodeId"]
        assert code.to_json() == json

    def test_to_from_json_temporary_schedule(self, access_code_json):
        auth = mock.create_autospec(Auth, spec_set=True)
        device_id = "__device_uuid__"
        access_code_id = "__access_code_uuid__"
        sched = TemporarySchedule(
            start=datetime(2022, 12, 25, 8, 30, 0),
            end=datetime(2022, 12, 25, 9, 0, 0),
        )
        json = deepcopy(access_code_json)
        json["activationSecs"] = 1671957000
        json["expirationSecs"] = 1671958800
        code = AccessCode(
            _auth=auth,
            name="Friendly name",
            code="0123",
            schedule=sched,
            device_id=device_id,
            access_code_id=access_code_id,
        )
        assert AccessCode.from_json(auth, json, device_id) == code

        # We don't send back the id because it's not mutable.
        del json["accesscodeId"]
        assert code.to_json() == json

    def test_refresh(self, access_code_json):
        auth = mock.create_autospec(Auth, spec_set=True)
        code = AccessCode.from_json(auth, access_code_json, "__device_uuid__")
        new_json = deepcopy(access_code_json)
        new_json["accessCode"] = 1122

        auth.request.return_value = mock.Mock(json=mock.Mock(return_value=new_json))
        code.refresh()

        auth.request.assert_called_once_with(
            "get", "devices/__device_uuid__/storage/accesscode/__access_code_uuid__"
        )
        assert code.code == "1122"

    def test_save(self, access_code_json):
        auth = mock.create_autospec(Auth, spec_set=True)
        code = AccessCode.from_json(auth, access_code_json, "__device_uuid__")
        code.code = 1122
        old_json = code.to_json()

        new_json = deepcopy(access_code_json)
        new_json["accessCode"] = 1122
        # Simulate another change that happened out of band.
        new_json["friendlyName"] = "New name"

        auth.request.return_value = mock.Mock(json=mock.Mock(return_value=new_json))
        code.save()

        auth.request.assert_called_once_with(
            "put",
            "devices/__device_uuid__/storage/accesscode/__access_code_uuid__",
            json=old_json,
        )
        assert code.code == "1122"
        # Ensure the name was updated.
        assert code.name == "New name"

    def test_delete(self, access_code_json):
        auth = mock.create_autospec(Auth, spec_set=True)
        code = AccessCode.from_json(auth, access_code_json, "__device_uuid__")
        auth.request.return_value = mock.Mock()
        code.delete()
        auth.request.assert_called_once_with(
            "delete", "devices/__device_uuid__/storage/accesscode/__access_code_uuid__"
        )
        assert code._auth is None
        assert code.access_code_id is None
        assert code.device_id is None
        assert code.disabled == True
