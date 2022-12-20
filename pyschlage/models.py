"""Data models for Schlage WiFi devices."""

from __future__ import annotations

from dataclasses import astuple, dataclass, field, fields
from datetime import datetime, timezone
from enum import Enum
from threading import Lock as Mutex

from .auth import Auth
from .exceptions import NotAuthenticatedError

_DEFAULT_UUID = "ffffffff-ffff-ffff-ffff-ffffffffffff"
_MIN_TIME = 0
_MAX_TIME = 0xFFFFFFFF
_MIN_HOUR = 0
_MIN_MINUTE = 0
_MAX_HOUR = 23
_MAX_MINUTE = 59
_ALL_DAYS = "7F"


@dataclass
class _Mutable:
    """Base class for models which have mutable state."""

    _mu: Mutex = field(init=False, repr=False, compare=False, default_factory=Mutex)
    _auth: Auth | None = field(default=None, repr=False)

    def __getstate__(self):
        state = self.__dict__.copy()
        del state["_mu"]
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self._mu = Mutex()

    def _update_with(self, json, *args, **kwargs):
        new_obj = self.__class__.from_json(self._auth, json, *args, **kwargs)
        with self._mu:
            for field in fields(new_obj):
                setattr(self, field.name, getattr(new_obj, field.name))


@dataclass
class TemporarySchedule:
    """A temporary schedule for when an AccessCode is enabled."""

    start: datetime
    end: datetime

    @classmethod
    def from_json(cls, json) -> TemporarySchedule:
        """Creates a TemporarySchedule from a JSON dict."""
        return TemporarySchedule(
            start=datetime.utcfromtimestamp(json["activationSecs"]),
            end=datetime.utcfromtimestamp(json["expirationSecs"]),
        )

    def to_json(self) -> dict:
        """Returns a JSON dict of this TemporarySchedule."""
        utc = timezone.utc
        return {
            "activationSecs": int(self.start.replace(tzinfo=timezone.utc).timestamp()),
            "expirationSecs": int(self.end.replace(tzinfo=timezone.utc).timestamp()),
        }


@dataclass
class DaysOfWeek:
    """Enabled status for each day of the week."""

    sun: bool = True
    mon: bool = True
    tue: bool = True
    wed: bool = True
    thu: bool = True
    fri: bool = True
    sat: bool = True

    @classmethod
    def from_str(cls, s) -> DaysOfWeek:
        """Creates a DaysOfWeek from a hex string."""
        n = int(s, 16)
        return cls(*[(n & (1 << i)) != 0 for i in reversed(range(7))])

    def to_str(self) -> str:
        """Returns the string representation."""
        n = 0
        for d in astuple(self):
            n = (n << 1) | d
        return hex(n).lstrip("0x").upper()


@dataclass
class RecurringSchedule:
    """A recurring schedule for when an AccessCode is enabled."""

    days_of_week: DaysOfWeek = field(default_factory=DaysOfWeek)
    start_hour: int = _MIN_HOUR
    start_minute: int = _MIN_MINUTE
    end_hour: int = _MAX_HOUR
    end_minute: int = _MAX_MINUTE

    @classmethod
    def from_json(cls, json) -> RecurringSchedule | None:
        """Creates a RecurringSchedule from a JSON dict."""
        if not json:
            return None
        if (
            json["daysOfWeek"] == _ALL_DAYS
            and json["startHour"] == _MIN_HOUR
            and json["startMinute"] == _MIN_MINUTE
            and json["endHour"] == _MAX_HOUR
            and json["endMinute"] == _MAX_MINUTE
        ):
            return None
        return cls(
            DaysOfWeek.from_str(json["daysOfWeek"]),
            json["startHour"],
            json["startMinute"],
            json["endHour"],
            json["endMinute"],
        )

    def to_json(self) -> dict:
        """Returns a JSON dict of this RecurringSchedule."""
        return {
            "daysOfWeek": self.days_of_week.to_str(),
            "startHour": self.start_hour,
            "startMinute": self.start_minute,
            "endHour": self.end_hour,
            "endMinute": self.end_minute,
        }


@dataclass
class AccessCode(_Mutable):
    """An access code for a lock."""

    name: str = ""
    code: str = ""
    schedule: TemporarySchedule | RecurringSchedule | None = None
    notify_on_use: bool = False
    disabled: bool = False
    device_id: str | None = field(default=None, repr=False)
    access_code_id: str | None = field(default=None, repr=False)

    @staticmethod
    def request_path(device_id: str, access_code_id: str | None = None) -> str:
        """Returns the request path for an AccessCode."""
        path = f"devices/{device_id}/storage/accesscode"
        if access_code_id:
            return f"{path}/{access_code_id}"
        return path

    @classmethod
    def from_json(cls, auth, json, device_id) -> AccessCode:
        """Creates an AccessCode from a JSON dict."""
        schedule = None
        if json["activationSecs"] == _MIN_TIME and json["expirationSecs"] == _MAX_TIME:
            schedule = RecurringSchedule.from_json(json["schedule1"])
        else:
            schedule = TemporarySchedule.from_json(json)

        return AccessCode(
            _auth=auth,
            device_id=device_id,
            access_code_id=json["accesscodeId"],
            name=json["friendlyName"],
            # TODO: We assume codes are always 4 characters.
            code=f"{json['accessCode']:04}",
            notify_on_use=bool(json["notification"]),
            disabled=bool(json.get("disabled", None)),
            schedule=schedule,
        )

    def to_json(self) -> dict:
        """Returns a JSON dict with this AccessCode's mutable properties."""
        json = {
            "friendlyName": self.name,
            "accessCode": int(self.code),
            "notification": int(self.notify_on_use),
            "disabled": int(self.disabled),
            "activationSecs": _MIN_TIME,
            "expirationSecs": _MAX_TIME,
            "schedule1": RecurringSchedule().to_json(),
        }
        if isinstance(self.schedule, RecurringSchedule):
            json["schedule1"] = self.schedule.to_json()
        elif self.schedule is not None:
            json.update(self.schedule.to_json())

        return json

    def refresh(self):
        """Refreshes internal state."""
        if self._auth is None:
            raise NotAuthenticatedError
        path = self.request_path(self.device_id, self.access_code_id)
        resp = self._auth.request("get", path)
        self._update_with(resp.json(), self.device_id)

    def save(self):
        """Commits changes to the access code."""
        if self._auth is None:
            raise NotAuthenticatedError
        path = self.request_path(self.device_id, self.access_code_id)
        resp = self._auth.request("put", path, json=self.to_json())
        self._update_with(resp.json(), self.device_id)

    def delete(self):
        """Deletes the access code."""
        if self._auth is None:
            raise NotAuthenticatedError
        path = self.request_path(self.device_id, self.access_code_id)
        self._auth.request("delete", path)
        self._auth = None
        self.access_code_id = None
        self.device_id = None
        self.disabled = True


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
class Lock(_Mutable):
    """A Schlage WiFi lock."""

    device_id: str = ""
    name: str = ""
    model_name: str = ""
    battery_level: int = 0
    is_locked: bool = False
    is_jammed: bool = False
    firmware_version: str = ""

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

    def access_codes(self) -> list[AccessCode]:
        """Fetches access codes for this lock."""
        return [
            AccessCode.from_json(self._auth, ac, self.device_id)
            for ac in self._auth.request(
                "get", AccessCode.request_path(self.device_id)
            ).json()
        ]

    def add_access_code(self, code: AccessCode):
        """Adds an access code to the lock."""
        if not self._auth:
            raise NotAuthenticatedError
        resp = self._auth.request(
            "post", AccessCode.request_path(self.device_id), json=code.to_json()
        )
        code._auth = self._auth
        code._update_with(resp.json(), self.device_id)
