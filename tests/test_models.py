from copy import deepcopy
from datetime import datetime
from unittest import mock

import pyschlage
from pyschlage import models

from .fixtures import ACCESS_CODE_JSON, LOCK_JSON


class TestAccessCode:
    def test_to_from_json(self):
        auth = mock.Mock()
        device_id = "__device_uuid__"
        access_code_id = "__access_code_uuid__"
        code = models.AccessCode(
            _auth=auth,
            name="Friendly name",
            code="0123",
            schedule=None,
            device_id=device_id,
            access_code_id=access_code_id,
        )
        assert models.AccessCode.from_json(auth, ACCESS_CODE_JSON, device_id) == code

        want_json = deepcopy(ACCESS_CODE_JSON)
        # We don't send back the id because it's not mutable.
        del want_json["accesscodeId"]
        assert code.to_json() == want_json

    def test_to_from_json_recurring_schedule(self):
        auth = mock.Mock()
        device_id = "__device_uuid__"
        access_code_id = "__access_code_uuid__"
        sched = models.RecurringSchedule(days_of_week=models.DaysOfWeek(mon=False))
        json = deepcopy(ACCESS_CODE_JSON)
        json["schedule1"] = sched.to_json()
        code = models.AccessCode(
            _auth=auth,
            name="Friendly name",
            code="0123",
            schedule=sched,
            device_id=device_id,
            access_code_id=access_code_id,
        )
        assert models.AccessCode.from_json(auth, json, device_id) == code

        # We don't send back the id because it's not mutable.
        del json["accesscodeId"]
        assert code.to_json() == json

    def test_to_from_json_temporary_schedule(self):
        auth = mock.Mock()
        device_id = "__device_uuid__"
        access_code_id = "__access_code_uuid__"
        sched = models.TemporarySchedule(
            start=datetime(2022, 12, 25, 8, 30, 0),
            end=datetime(2022, 12, 25, 9, 0, 0),
        )
        json = deepcopy(ACCESS_CODE_JSON)
        json["activationSecs"] = 1671957000
        json["expirationSecs"] = 1671958800
        code = models.AccessCode(
            _auth=auth,
            name="Friendly name",
            code="0123",
            schedule=sched,
            device_id=device_id,
            access_code_id=access_code_id,
        )
        assert models.AccessCode.from_json(auth, json, device_id) == code

        # We don't send back the id because it's not mutable.
        del json["accesscodeId"]
        assert code.to_json() == json

    def test_refresh(self):
        auth = mock.Mock()
        code = models.AccessCode.from_json(auth, ACCESS_CODE_JSON, "__device_uuid__")
        new_json = deepcopy(ACCESS_CODE_JSON)
        new_json["accessCode"] = 1122

        auth.request.return_value = mock.Mock(json=mock.Mock(return_value=new_json))
        code.refresh()

        auth.request.assert_called_once_with(
            "get", "devices/__device_uuid__/storage/accesscode/__access_code_uuid__"
        )
        assert code.code == "1122"

    def test_save(self):
        auth = mock.Mock()
        code = models.AccessCode.from_json(auth, ACCESS_CODE_JSON, "__device_uuid__")
        code.code = 1122
        old_json = code.to_json()

        new_json = deepcopy(ACCESS_CODE_JSON)
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

    def test_delete(self):
        auth = mock.Mock()
        code = models.AccessCode.from_json(auth, ACCESS_CODE_JSON, "__device_uuid__")
        auth.request.return_value = mock.Mock()
        code.delete()
        auth.request.assert_called_once_with(
            "delete", "devices/__device_uuid__/storage/accesscode/__access_code_uuid__"
        )
        assert code._auth is None
        assert code.access_code_id is None
        assert code.device_id is None
        assert code.disabled == True


class TestLock:
    def test_from_json(self):
        auth = mock.Mock()
        lock = pyschlage.Lock.from_json(auth, LOCK_JSON)
        assert lock._auth == auth
        assert lock.device_id == "__device_uuid__"
        assert lock.name == "Door Lock"
        assert lock.model_name == "__model_name__"
        assert lock.battery_level == 95
        assert lock.is_locked
        assert not lock.is_jammed
        assert lock.firmware_version == "10.00.00264232"

    def test_from_json_is_jammed(self):
        auth = mock.Mock()
        json = deepcopy(LOCK_JSON)
        json["attributes"]["lockState"] = 2
        lock = pyschlage.Lock.from_json(auth, json)
        assert not lock.is_locked
        assert lock.is_jammed

    def test_update(self):
        auth = mock.Mock()
        lock = pyschlage.Lock.from_json(auth, LOCK_JSON)
        new_json = deepcopy(LOCK_JSON)
        new_json["name"] = "<NAME>"

        auth.request.return_value = mock.Mock(json=mock.Mock(return_value=new_json))
        lock.update()

        auth.request.assert_called_once_with("get", "devices/__device_uuid__")
        assert lock.name == "<NAME>"

    def test_lock(self):
        auth = mock.Mock()
        initial_json = deepcopy(LOCK_JSON)
        initial_json["attributes"]["lockState"] = 0
        lock = pyschlage.Lock.from_json(auth, LOCK_JSON)

        new_json = deepcopy(LOCK_JSON)
        new_json["attributes"]["lockState"] = 1

        auth.request.return_value = mock.Mock(json=mock.Mock(return_value=new_json))
        lock.lock()

        auth.request.assert_called_once_with(
            "put", "devices/__device_uuid__", json={"attributes": {"lockState": 1}}
        )
        assert lock.is_locked

    def test_unlock(self):
        auth = mock.Mock()
        initial_json = deepcopy(LOCK_JSON)
        initial_json["attributes"]["lockState"] = 1
        lock = pyschlage.Lock.from_json(auth, LOCK_JSON)

        new_json = deepcopy(LOCK_JSON)
        new_json["attributes"]["lockState"] = 0

        auth.request.return_value = mock.Mock(json=mock.Mock(return_value=new_json))
        lock.unlock()

        auth.request.assert_called_once_with(
            "put", "devices/__device_uuid__", json={"attributes": {"lockState": 0}}
        )
        assert not lock.is_locked

    def test_access_codes(self):
        auth = mock.Mock()
        lock = models.Lock.from_json(auth, LOCK_JSON)

        auth.request.return_value = mock.Mock(
            json=mock.Mock(return_value=[ACCESS_CODE_JSON])
        )
        codes = lock.access_codes()

        auth.request.assert_called_once_with(
            "get", "devices/__device_uuid__/storage/accesscode"
        )
        assert codes == [
            models.AccessCode.from_json(auth, ACCESS_CODE_JSON, lock.device_id)
        ]

    def test_add_access_code(self):
        auth = mock.Mock()
        lock = models.Lock.from_json(auth, LOCK_JSON)
        code = models.AccessCode.from_json(auth, ACCESS_CODE_JSON, lock.device_id)
        # Users should not set these.
        code._auth = None
        code.access_code_id = None
        code.device_id = None
        json = code.to_json()

        auth.request.return_value = mock.Mock(
            json=mock.Mock(return_value=ACCESS_CODE_JSON)
        )
        lock.add_access_code(code)

        auth.request.assert_called_once_with(
            "post",
            "devices/__device_uuid__/storage/accesscode",
            json=json,
        )
        assert code._auth == auth
        assert code.device_id == lock.device_id
        assert code.access_code_id == "__access_code_uuid__"
