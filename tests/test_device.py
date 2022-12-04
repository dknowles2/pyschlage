from copy import deepcopy
from unittest import mock

import pyschlage


DEVICE_JSON = {
    "CAT": "01234",
    "SAT": "98765",
    "attributes": {
        "CAT": "01234",
        "SAT": "98765",
        "accessCodeLength": 4,
        "actAlarmBuzzerEnabled": 0,
        "actAlarmState": 0,
        "actuationCurrentMax": 226,
        "alarmSelection": 0,
        "alarmSensitivity": 0,
        "alarmState": 0,
        "autoLockTime": 0,
        "batteryChangeDate": 1669017530,
        "batteryLevel": 95,
        "batteryLowState": 0,
        "batterySaverConfig": {
            "activePeriod": [],
            "enabled": 0,
        },
        "batterySaverState": 0,
        "beeperEnabled": 1,
        "bleFirmwareVersion": "0118.000103.015",
        "diagnostics": {},
        "firmwareUpdate": {"status": {"additionalInfo": None, "updateStatus": None}},
        "homePosCurrentMax": 153,
        "keypadFirmwareVersion": "03.00.00250052",
        "lockAndLeaveEnabled": 1,
        "lockState": 1,
        "lockStateMetadata": {
            "UUID": None,
            "actionType": "periodicDeepQuery",
            "clientId": None,
            "name": None,
        },
        "macAddress": "AA:BB:CC:00:11:22",
        "mainFirmwareVersion": "10.00.00264232",
        "mode": 2,
        "modelName": "__model_name__",
        "periodicDeepQueryTimeSetting": 60,
        "psPollEnabled": 1,
        "serialNumber": "d34db33f",
        "timezone": -20,
        "wifiFirmwareVersion": "03.15.00.01",
        "wifiRssi": -42,
    },
    "connected": True,
    "connectivityUpdated": "2022-12-04T20:58:22.000Z",
    "created": "2020-04-05T21:53:11.000Z",
    "deviceId": "__device_uuid__",
    "devicetypeId": "be489wifi",
    "lastUpdated": "2022-12-04T20:58:22.000Z",
    "macAddress": "AA:BB:CC:00:11:22",
    "modelName": "__model_name__",
    "name": "Door Lock",
    "physicalId": "serial-number",
    "relatedDevices": [],
    "role": "owner",
    "serialNumber": "serial-number",
    "timezone": -20,
    "users": [
        {
            "email": "asdf@asdf.com",
            "friendlyName": "asdf",
            "identityId": "user-uuid",
            "role": "owner",
        }
    ],
}


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

    auth.request.assert_called_once_with("put", "__device_uuid__", json={"attributes": {"lockState": 1}})
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

    auth.request.assert_called_once_with("put", "__device_uuid__", json={"attributes": {"lockState": 0}})
    assert not device.is_locked
