from copy import deepcopy
from datetime import datetime
from unittest import mock

import pyschlage
from pyschlage.code import AccessCode
from pyschlage.lock import Lock

from .fixtures import ACCESS_CODE_JSON, LOCK_JSON


class TestLock:
    def test_from_json(self):
        auth = mock.Mock()
        lock = Lock.from_json(auth, LOCK_JSON)
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
        lock = Lock.from_json(auth, json)
        assert not lock.is_locked
        assert lock.is_jammed

    def test_refresh(self):
        auth = mock.Mock()
        lock = Lock.from_json(auth, LOCK_JSON)
        new_json = deepcopy(LOCK_JSON)
        new_json["name"] = "<NAME>"

        auth.request.return_value = mock.Mock(json=mock.Mock(return_value=new_json))
        lock.refresh()

        auth.request.assert_called_once_with("get", "devices/__device_uuid__")
        assert lock.name == "<NAME>"

    def test_lock(self):
        auth = mock.Mock()
        initial_json = deepcopy(LOCK_JSON)
        initial_json["attributes"]["lockState"] = 0
        lock = Lock.from_json(auth, LOCK_JSON)

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
        lock = Lock.from_json(auth, LOCK_JSON)

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
        lock = Lock.from_json(auth, LOCK_JSON)

        auth.request.return_value = mock.Mock(
            json=mock.Mock(return_value=[ACCESS_CODE_JSON])
        )
        codes = lock.access_codes()

        auth.request.assert_called_once_with(
            "get", "devices/__device_uuid__/storage/accesscode"
        )
        assert codes == [AccessCode.from_json(auth, ACCESS_CODE_JSON, lock.device_id)]

    def test_add_access_code(self):
        auth = mock.Mock()
        lock = Lock.from_json(auth, LOCK_JSON)
        code = AccessCode.from_json(auth, ACCESS_CODE_JSON, lock.device_id)
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
