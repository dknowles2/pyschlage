from copy import deepcopy
from unittest import mock

from pyschlage.code import AccessCode
from pyschlage.lock import Lock


class TestLock:
    def test_from_json(self, mock_auth, lock_json):
        lock = Lock.from_json(mock_auth, lock_json)
        assert lock._auth == mock_auth
        assert lock.device_id == "__wifi_uuid__"
        assert lock.name == "Door Lock"
        assert lock.model_name == "__model_name__"
        assert lock.device_type == "be489wifi"
        assert lock.battery_level == 95
        assert lock.is_locked
        assert lock._cat == "01234"
        assert lock.is_jammed == False
        assert lock.firmware_version == "10.00.00264232"
        assert lock.mac_address == "AA:BB:CC:00:11:22"

    def test_from_json_is_jammed(self, mock_auth, lock_json):
        lock_json["attributes"]["lockState"] = 2
        lock = Lock.from_json(mock_auth, lock_json)
        assert lock.is_locked == False
        assert lock.is_jammed

    def test_from_json_wifi_lock_unavailable(
        self, mock_auth, wifi_lock_unavailable_json
    ):
        lock = Lock.from_json(mock_auth, wifi_lock_unavailable_json)
        assert lock.battery_level is None
        assert lock.firmware_version is None
        assert lock.is_locked is None
        assert lock.is_jammed is None

    def test_refresh(self, mock_auth, lock_json):
        lock = Lock.from_json(mock_auth, lock_json)
        lock_json["name"] = "<NAME>"

        mock_auth.request.return_value = mock.Mock(
            json=mock.Mock(return_value=lock_json)
        )
        lock.refresh()

        mock_auth.request.assert_called_once_with("get", "devices/__wifi_uuid__")
        assert lock.name == "<NAME>"

    def test_lock_wifi(self, mock_auth, wifi_lock_json):
        initial_json = deepcopy(wifi_lock_json)
        initial_json["attributes"]["lockState"] = 0
        lock = Lock.from_json(mock_auth, initial_json)

        new_json = deepcopy(wifi_lock_json)
        new_json["attributes"]["lockState"] = 1

        mock_auth.request.return_value = mock.Mock(
            json=mock.Mock(return_value=new_json)
        )
        lock.lock()

        mock_auth.request.assert_called_once_with(
            "put", "devices/__wifi_uuid__", json={"attributes": {"lockState": 1}}
        )
        assert lock.is_locked

    def test_unlock_wifi(self, mock_auth, wifi_lock_json):
        initial_json = deepcopy(wifi_lock_json)
        initial_json["attributes"]["lockState"] = 1
        lock = Lock.from_json(mock_auth, initial_json)

        new_json = deepcopy(wifi_lock_json)
        new_json["attributes"]["lockState"] = 0

        mock_auth.request.return_value = mock.Mock(
            json=mock.Mock(return_value=new_json)
        )
        lock.unlock()

        mock_auth.request.assert_called_once_with(
            "put", "devices/__wifi_uuid__", json={"attributes": {"lockState": 0}}
        )
        assert lock.is_locked == False

    def test_lock_ble(self, mock_auth, ble_lock_json):
        lock = Lock.from_json(mock_auth, ble_lock_json)
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
        mock_auth.request.assert_called_once_with(
            "post", "devices/__ble_uuid__/commands", json=command_json
        )
        assert lock.is_locked

    def test_unlock_ble(self, mock_auth, ble_lock_json):
        lock = Lock.from_json(mock_auth, ble_lock_json)
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
        mock_auth.request.assert_called_once_with(
            "post", "devices/__ble_uuid__/commands", json=command_json
        )
        assert lock.is_locked == False

    def test_access_codes(self, mock_auth, lock_json, access_code_json):
        lock = Lock.from_json(mock_auth, lock_json)

        mock_auth.request.return_value = mock.Mock(
            json=mock.Mock(return_value=[access_code_json])
        )
        codes = lock.access_codes()

        mock_auth.request.assert_called_once_with(
            "get", "devices/__wifi_uuid__/storage/accesscode"
        )
        assert codes == [
            AccessCode.from_json(mock_auth, access_code_json, lock.device_id)
        ]

    def test_add_access_code(self, mock_auth, lock_json, access_code_json):
        lock = Lock.from_json(mock_auth, lock_json)
        code = AccessCode.from_json(mock_auth, access_code_json, lock.device_id)
        # Users should not set these.
        code._auth = None
        code.access_code_id = None
        code.device_id = None
        json = code.to_json()

        mock_auth.request.return_value = mock.Mock(
            json=mock.Mock(return_value=access_code_json)
        )
        lock.add_access_code(code)

        mock_auth.request.assert_called_once_with(
            "post",
            "devices/__wifi_uuid__/storage/accesscode",
            json=json,
        )
        assert code._auth == mock_auth
        assert code.device_id == lock.device_id
        assert code.access_code_id == "__access_code_uuid__"
