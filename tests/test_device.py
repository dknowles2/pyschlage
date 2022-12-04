from copy import deepcopy
from unittest import mock

import pyschlage

from .fixtures import DEVICE_JSON


def test_from_json():
    auth = mock.Mock()
    device = pyschlage.Device.from_json(auth, DEVICE_JSON)
    assert device._auth == auth
    assert device.device_id == "__device_uuid__"
    assert device.name == "Door Lock"
    assert device.model_name == "__model_name__"
    assert device.battery_level == 95
    assert device.is_locked
    assert not device.is_jammed
    assert device.firmware_version == "10.00.00264232"


def test_from_json_is_jammed():
    auth = mock.Mock()
    json = deepcopy(DEVICE_JSON)
    json["attributes"]["lockState"] = 2
    device = pyschlage.Device.from_json(auth, json)
    assert not device.is_locked
    assert device.is_jammed


def test_update():
    auth = mock.Mock()
    device = pyschlage.Device.from_json(auth, DEVICE_JSON)
    new_json = deepcopy(DEVICE_JSON)
    new_json["name"] = "<NAME>"

    auth.request.return_value = mock.Mock(json=mock.Mock(return_value=new_json))
    device.update()

    auth.request.assert_called_once_with("get", "__device_uuid__")
    assert device.name == "<NAME>"


def test_lock():
    auth = mock.Mock()
    initial_json = deepcopy(DEVICE_JSON)
    initial_json["attributes"]["lockState"] = 0
    device = pyschlage.Device.from_json(auth, DEVICE_JSON)

    new_json = deepcopy(DEVICE_JSON)
    new_json["attributes"]["lockState"] = 1

    auth.request.return_value = mock.Mock(json=mock.Mock(return_value=new_json))
    device.lock()

    auth.request.assert_called_once_with(
        "put", "__device_uuid__", json={"attributes": {"lockState": 1}}
    )
    assert device.is_locked


def test_unlock():
    auth = mock.Mock()
    initial_json = deepcopy(DEVICE_JSON)
    initial_json["attributes"]["lockState"] = 1
    device = pyschlage.Device.from_json(auth, DEVICE_JSON)

    new_json = deepcopy(DEVICE_JSON)
    new_json["attributes"]["lockState"] = 0

    auth.request.return_value = mock.Mock(json=mock.Mock(return_value=new_json))
    device.unlock()

    auth.request.assert_called_once_with(
        "put", "__device_uuid__", json={"attributes": {"lockState": 0}}
    )
    assert not device.is_locked
