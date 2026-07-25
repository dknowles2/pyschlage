from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pytest import fixture

from pyschlage.client import Schlage
from pyschlage.code import AccessCode
from pyschlage.lock import Lock
from pyschlage.log import LockLog
from pyschlage.notification import ON_UNLOCK_ACTION, Notification

USER_ID = "<user-id>"


@dataclass(frozen=True)
class RecordedRequest:
    """A request captured by :class:`FakeTransport`."""

    method: str
    path: str
    params: dict[str, Any] | None = None
    json: Any = None


@dataclass
class FakeTransport:
    """A :class:`pyschlage.Transport` that serves canned responses.

    Lets client tests assert on the exact requests issued without mocking HTTP
    or the auth stack.
    """

    responses: dict[tuple[str, str], Any] = field(default_factory=dict)
    requests: list[RecordedRequest] = field(default_factory=list)

    def add(self, method: str, path: str, response: Any) -> None:
        self.responses[(method, path)] = response

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        self.requests.append(RecordedRequest(method, path, params, json))
        key = (method, path)
        if key not in self.responses:
            raise AssertionError(f"unexpected request: {method} {path}")
        return self.responses[key]


@fixture
def transport() -> FakeTransport:
    return FakeTransport()


@fixture
def schlage(transport: FakeTransport) -> Schlage:
    return Schlage(transport, USER_ID)


@fixture
def lock_users_json() -> list[dict]:
    return [
        {
            "consentRecords": [],
            "created": "2022-12-24T20:00:00.000Z",
            "email": "asdf@asdf.com",
            "friendlyName": "asdf",
            "identityId": "user-uuid",
            "role": "owner",
            "lastUpdated": "2022-12-24T20:00:00.000Z",
        },
        {
            "consentRecords": [],
            "created": "2022-12-24T20:00:00.000Z",
            "email": "foo@bar.xyz",
            "friendlyName": "Foo Bar",
            "identityId": "foo-bar-uuid",
            "role": "guest",
            "lastUpdated": "2022-12-24T20:00:00.000Z",
        },
    ]


@fixture
def wifi_lock_json(lock_users_json):
    return {
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
            "firmwareUpdate": {
                "status": {"additionalInfo": None, "updateStatus": None}
            },
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
        "deviceId": "__wifi_uuid__",
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
        "users": lock_users_json,
    }


@fixture
def wifi_lock_unavailable_json(wifi_lock_json):
    keep = ("modelName", "serialNumber", "macAddress", "SAT", "CAT")
    for k in list(wifi_lock_json["attributes"].keys()):
        if k not in keep:
            del wifi_lock_json["attributes"][k]
    return wifi_lock_json


@fixture
def lock_json(wifi_lock_json):
    return wifi_lock_json


@fixture
def wifi_lock(wifi_lock_json: dict) -> Lock:
    return Lock.from_json(wifi_lock_json)


@fixture
def ble_lock_json(lock_users_json):
    return {
        "CAT": "abcdef",
        "SAT": "ghijkl",
        "attributes": {
            "CAT": "abcdef",
            "SAT": "ghijkl",
            "accessCodeLength": 4,
            "adminOnlyEnabled": 0,
            "alarmSelection": 0,
            "alarmSensitivity": 0,
            "alarmState": 0,
            "autoLockTime": 240,
            "batteryLevel": 66,
            "batteryLowState": 0,
            "beeperEnabled": 1,
            "hardwareVersion": "1.3.0",
            "lastTalkedTime": "2022-12-20T22:46:11Z",
            "lockAndLeaveEnabled": 1,
            "lockState": 1,
            "macAddress": "EA:10:CA:87:19:F6",
            "mainFirmwareVersion": "004.031.000",
            "manufacturerName": "Schlage ",
            "modelName": "BE479CEN619",
            "name": "BLE Lock",
            "profileVersion": "1.1",
            "serialNumber": "<ble-sn>",
            "timezone": -60,
        },
        "connected": False,
        "connectivityUpdated": "2022-12-20T23:02:35.000Z",
        "created": "2021-03-03T20:19:18.000Z",
        "deviceId": "__ble_uuid__",
        "devicetypeId": "be479",
        "lastUpdated": "2022-12-20T23:02:35.000Z",
        "macAddress": "EA:10:CA:87:19:F6",
        "modelName": "BE479CEN619",
        "name": "BLE Lock",
        "physicalId": "ea:10:ca:87:19:f6",
        "relatedDevices": [{"deviceId": "__bridge_uuid__"}],
        "role": "owner",
        "serialNumber": "<ble-sn>",
        "timezone": -60,
        "users": lock_users_json,
    }


@fixture
def ble_lock(ble_lock_json: dict) -> Lock:
    return Lock.from_json(ble_lock_json)


@fixture
def access_code_json():
    return {
        "accessCode": 123,
        "accesscodeId": "__access_code_uuid__",
        "accessCodeLength": 4,
        "activationSecs": 0,
        "disabled": 0,
        "expirationSecs": 4294967295,
        "friendlyName": "Access code name",
        "notification": 0,
        "schedule1": {
            "daysOfWeek": "7F",
            "endHour": 23,
            "endMinute": 59,
            "startHour": 0,
            "startMinute": 0,
        },
    }


@fixture
def access_code(access_code_json: dict, wifi_lock: Lock) -> AccessCode:
    return AccessCode.from_json(
        access_code_json,
        device_id=wifi_lock.device_id,
        device_type=wifi_lock.device_type,
    )


@fixture
def notification_json() -> dict[str, Any]:
    return {
        "notificationId": "<user-id>___access_code_uuid__",
        "userId": "<user-id>",
        "deviceId": "__wifi_uuid__",
        "notificationDefinitionId": ON_UNLOCK_ACTION,
        "filterValue": "Access code name",
        "active": True,
        "createdAt": "2023-03-01T17:26:47.366Z",
        "updatedAt": "2023-03-01T17:26:47.366Z",
    }


@fixture
def notification(notification_json) -> Notification:
    return Notification.from_json(notification_json)


@fixture
def log_json() -> dict[str, Any]:
    return {
        "createdAt": "2023-03-01T17:26:47.366Z",
        "deviceId": "__device_uuid__",
        "logId": "__log_uuid__",
        "message": {
            "accessorUuid": "ffffffff-ffff-ffff-ffff-ffffffffffff",
            "action": 2,
            "clientId": None,
            "eventCode": 9999,
            "keypadUuid": "ffffffff-ffff-ffff-ffff-ffffffffffff",
            "secondsSinceEpoch": 1677691601,
        },
        "timestamp": "2023-03-01T17:26:41.001Z",
        "ttl": "2023-03-31T17:26:47.000Z",
        "type": "DEVICE_LOG",
        "updatedAt": "2023-03-01T17:26:47.366Z",
    }


@fixture
def lock_log(log_json: dict[str, Any]) -> LockLog:
    return LockLog.from_json(log_json)
