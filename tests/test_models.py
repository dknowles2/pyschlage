from copy import deepcopy
from unittest import mock

import pyschlage

from .fixtures import LOCK_JSON


def test_from_json():
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


def test_from_json_is_jammed():
    auth = mock.Mock()
    json = deepcopy(LOCK_JSON)
    json["attributes"]["lockState"] = 2
    lock = pyschlage.Lock.from_json(auth, json)
    assert not lock.is_locked
    assert lock.is_jammed


def test_update():
    auth = mock.Mock()
    lock = pyschlage.Lock.from_json(auth, LOCK_JSON)
    new_json = deepcopy(LOCK_JSON)
    new_json["name"] = "<NAME>"

    auth.request.return_value = mock.Mock(json=mock.Mock(return_value=new_json))
    lock.update()

    auth.request.assert_called_once_with("get", "devices/__device_uuid__")
    assert lock.name == "<NAME>"


def test_lock():
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


def test_unlock():
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
