from copy import deepcopy
from datetime import datetime
from unittest import mock

import pyschlage
from pyschlage.code import AccessCode
from pyschlage.lock import Lock


class TestLock:
    def test_from_json(self, lock_json):
        auth = mock.Mock()
        lock = Lock.from_json(auth, lock_json)
        assert lock._auth == auth
        assert lock.device_id == "__wifi_uuid__"
        assert lock.name == "Door Lock"
        assert lock.model_name == "__model_name__"
        assert lock.device_type == "be489wifi"
        assert lock.battery_level == 95
        assert lock.is_locked
        assert lock._cat == "01234"
        assert not lock.is_jammed
        assert lock.firmware_version == "10.00.00264232"

    def test_from_json_is_jammed(self, lock_json):
        auth = mock.Mock()
        lock_json["attributes"]["lockState"] = 2
        lock = Lock.from_json(auth, lock_json)
        assert not lock.is_locked
        assert lock.is_jammed

    def test_refresh(self, lock_json):
        auth = mock.Mock()
        lock = Lock.from_json(auth, lock_json)
        lock_json["name"] = "<NAME>"

        auth.request.return_value = mock.Mock(json=mock.Mock(return_value=lock_json))
        lock.refresh()

        auth.request.assert_called_once_with("get", "devices/__wifi_uuid__")
        assert lock.name == "<NAME>"

    def test_lock_wifi(self, wifi_lock_json):
        auth = mock.Mock()
        initial_json = deepcopy(wifi_lock_json)
        initial_json["attributes"]["lockState"] = 0
        lock = Lock.from_json(auth, initial_json)

        new_json = deepcopy(wifi_lock_json)
        new_json["attributes"]["lockState"] = 1

        auth.request.return_value = mock.Mock(json=mock.Mock(return_value=new_json))
        lock.lock()

        auth.request.assert_called_once_with(
            "put", "devices/__wifi_uuid__", json={"attributes": {"lockState": 1}}
        )
        assert lock.is_locked

    def test_unlock_wifi(self, wifi_lock_json):
        auth = mock.Mock()
        initial_json = deepcopy(wifi_lock_json)
        initial_json["attributes"]["lockState"] = 1
        lock = Lock.from_json(auth, initial_json)

        new_json = deepcopy(wifi_lock_json)
        new_json["attributes"]["lockState"] = 0

        auth.request.return_value = mock.Mock(json=mock.Mock(return_value=new_json))
        lock.unlock()

        auth.request.assert_called_once_with(
            "put", "devices/__wifi_uuid__", json={"attributes": {"lockState": 0}}
        )
        assert not lock.is_locked

    def test_lock_ble(self, ble_lock_json):
        auth = mock.Mock(user_id="<user-id>")
        lock = Lock.from_json(auth, ble_lock_json)
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
        auth.request.assert_called_once_with(
            "post", "devices/__ble_uuid__/commands", json=command_json
        )
        assert lock.is_locked

    def test_unlock_ble(self, ble_lock_json):
        auth = mock.Mock(user_id="<user-id>")
        lock = Lock.from_json(auth, ble_lock_json)
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
        auth.request.assert_called_once_with(
            "post", "devices/__ble_uuid__/commands", json=command_json
        )
        assert not lock.is_locked

    def test_access_codes(self, lock_json, access_code_json):
        auth = mock.Mock()
        lock = Lock.from_json(auth, lock_json)

        auth.request.return_value = mock.Mock(
            json=mock.Mock(return_value=[access_code_json])
        )
        codes = lock.access_codes()

        auth.request.assert_called_once_with(
            "get", "devices/__wifi_uuid__/storage/accesscode"
        )
        assert codes == [AccessCode.from_json(auth, access_code_json, lock.device_id)]

    def test_add_access_code(self, lock_json, access_code_json):
        auth = mock.Mock()
        lock = Lock.from_json(auth, lock_json)
        code = AccessCode.from_json(auth, access_code_json, lock.device_id)
        # Users should not set these.
        code._auth = None
        code.access_code_id = None
        code.device_id = None
        json = code.to_json()

        auth.request.return_value = mock.Mock(
            json=mock.Mock(return_value=access_code_json)
        )
        lock.add_access_code(code)

        auth.request.assert_called_once_with(
            "post",
            "devices/__wifi_uuid__/storage/accesscode",
            json=json,
        )
        assert code._auth == auth
        assert code.device_id == lock.device_id
        assert code.access_code_id == "__access_code_uuid__"
