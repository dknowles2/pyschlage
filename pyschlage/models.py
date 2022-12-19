"""Data models for Schlage WiFi devices."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from enum import Enum
from threading import Lock as Mutex

from .auth import Auth

_DEFAULT_UUID = "ffffffff-ffff-ffff-ffff-ffffffffffff"


class LogEvent(Enum):

    UNKNOWN = -1
    UNKNOWN0 = 0
    LOCKED_BY_KEYPAD = 1
    UNLOCKED_BY_KEYPAD = 2
    LOCKED_BY_THUMBTURN = 3
    UNLOCKED_BY_THUMBTURN = 4
    LOCKED_BY_SCHLAGE_BUTTON = 5
    LOCKED_BY_MOBILE_DEVICE = 6
    UNLOCKED_BY_MOBILE_DEVICE = 7
    LOCKED_BY_TIME = 8
    UNLOCKED_BY_TIME = 9
    LOCK_JAMMED = 10
    KEYPAD_DISABLED_INVALID_CODE = 11
    ALARM_TRIGGERED = 12
    ACCESS_CODE_USER_ADDED = 14
    ACCESS_CODE_USER_DELETED = 15
    MOBILE_USER_ADDED = 16
    MOBILE_USER_DELETED = 17
    ADMIN_PRIVILEGE_ADDED = 18
    ADMIN_PRIVILEGE_DELETED = 19
    FIRMWARE_UPDATED = 20
    LOW_BATTERY_INDICATED = 21
    BATTERIES_REPLACED = 22
    FORCED_ENTRY_ALARM_SILENCED = 23
    HALL_SENSOR_COMM_ERROR = 27
    FDR_FAILED = 28
    CRITICAL_BATTERY_STATE = 29
    ALL_ACCESS_CODE_DELETED = 30
    FIRMWARE_UPDATE_FAILED = 32
    BT_FW_DOWNLOAD_FAILED = 33
    WIFI_FW_DOWNLOAD_FAILED = 34
    KEYPAD_DISCONNECTED = 35
    WIFI_AP_DISCONNECT = 36
    WIFI_HOST_DISCONNECT = 37
    WIFI_AP_CONNECT = 38
    WIFI_HOST_CONNECT = 39
    USER_DB_FAILURE = 40
    PASSAGE_MODE_ACTIVATED = 48
    PASSAGE_MODE_DEACTIVATED = 49
    UNLOCKED_BY_APPLE_KEY = 52
    LOCKED_BY_APPLE_KEY = 53
    MOTOR_JAMMED_ON_FAIL = 54
    MOTOR_JAMMED_OFF_FAIL = 55
    MOTOR_JAMMED_RETRIES_EXCEEDED = 56
    HISTORY_CLEARED = 255

    @classmethod
    def _missing_(cls, value):
        return cls.UNKNOWN


@dataclass
class LogData:

    seconds_since_epoch: int
    keypad_uuid: str | None
    accessor_uuid: str | None
    event_code: LogEvent

    @classmethod
    def from_json(cls, json):
        none_if_default = lambda x: None if x == _DEFAULT_UUID else x
        return cls(
            seconds_since_epoch=json["secondsSinceEpoch"],
            keypad_uuid=none_if_default(json["keypadUuid"]),
            accessor_uuid=none_if_default(json["accessorUuid"]),
            event_code=LogEvent(json["eventCode"]),
        )


@dataclass
class LockLog:
    """A lock log entry."""

    # TODO: This should be a datetime
    created_at: str
    device_id: str
    log_id: str
    message: LogData

    @classmethod
    def from_json(cls, json):
        return cls(
            created_at=json["createdAt"],
            device_id=json["deviceId"],
            log_id=json["logId"],
            message=LogData.from_json(json["message"]),
        )


@dataclass
class Lock:
    """A Schlage WiFi lock."""

    _mu: Mutex = field(init=False, repr=False, default_factory=Mutex)
    _auth: Auth | None
    device_id: str
    name: str
    model_name: str
    battery_level: int
    is_locked: bool
    is_jammed: bool
    firmware_version: str

    def __getstate__(self):
        state = self.__dict__.copy()
        del state["_mu"]
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self._mu = Mutex()

    @classmethod
    def from_json(cls, auth, json):
        """Creates a Lock from a JSON object."""
        return cls(
            _auth=auth,
            device_id=json["deviceId"],
            name=json["name"],
            model_name=json["modelName"],
            battery_level=json["attributes"]["batteryLevel"],
            is_locked=json["attributes"]["lockState"] == 1,
            is_jammed=json["attributes"]["lockState"] == 2,
            firmware_version=json["attributes"]["mainFirmwareVersion"],
        )

    def _update_with(self, json):
        new_obj = Lock.from_json(self._auth, json)
        with self._mu:
            for field in fields(new_obj):
                setattr(self, field.name, getattr(new_obj, field.name))

    def update(self):
        """Updates the current device state."""
        self._update_with(self._auth.request("get", f"devices/{self.device_id}").json())

    def _toggle(self, lock_state):
        self._update_with(
            self._auth.request(
                "put",
                f"devices/{self.device_id}",
                json={"attributes": {"lockState": lock_state}},
            ).json()
        )

    def lock(self):
        """Locks the device."""
        self._toggle(1)

    def unlock(self):
        """Unlocks the device."""
        self._toggle(0)

    def logs(self, limit: int | None = None, sort_desc: bool = False) -> list[LockLog]:
        """Fetches activity logs for the lock."""
        params = {}
        if limit:
            params["limit"] = limit
        if sort_desc:
            params["sort"] = "desc"
        json = self._auth.request(
            "get", f"devices/{self.device_id}/logs", params=params
        ).json()
        return [LockLog.from_json(l) for l in json]
