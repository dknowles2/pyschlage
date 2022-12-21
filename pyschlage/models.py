"""Data models for Schlage WiFi devices."""

from __future__ import annotations

from dataclasses import astuple, dataclass, field, fields
from datetime import datetime, timezone
from threading import Lock as Mutex
import time

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
        path = f"{Lock.request_path(device_id)}/storage/accesscode"
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
        """Refreshes the AccessCode state."""
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


LOG_EVENT_TYPES = {
    -1: "Unknown",
    0: "Unknown",
    1: "Locked by keypad",
    2: "Unlocked by keypad",
    3: "Locked by thumbturn",
    4: "Unlocked by thumbturn",
    5: "Locked by Schlage button",
    6: "Locked by mobile device",
    7: "Unlocked by mobile device",
    8: "Locked by time",
    9: "Unlocked by time",
    10: "Lock jammed",
    11: "Keypad disabled invalid code",
    12: "Alarm triggered",
    14: "Access code user added",
    15: "Access code user deleted",
    16: "Mobile user added",
    17: "Mobile user deleted",
    18: "Admin privilege added",
    19: "Admin privilege deleted",
    20: "Firmware updated",
    21: "Low battery indicated",
    22: "Batteries replaced",
    23: "Forced entry alarm silenced",
    27: "Hall sensor comm error",
    28: "FDR failed",
    29: "Critical battery state",
    30: "All access code deleted",
    32: "Firmware update failed",
    33: "Bluetooth firmware download failed",
    34: "WiFi firmware download failed",
    35: "Keypad disconnected",
    36: "WiFi AP disconnect",
    37: "WiFi host disconnect",
    38: "WiFi AP connect",
    39: "WiFi host connect",
    40: "User DB failure",
    48: "Passage mode activated",
    49: "Passage mode deactivated",
    52: "Unlocked by Apple key",
    53: "Locked by Apple key",
    54: "Motor jammed on fail",
    55: "Motor jammed off fail",
    56: "Motor jammed retries exceeded",
    255: "History cleared",
}


def _utc2local(utc: datetime) -> datetime:
    """Converts a UTC datetime to localtime."""
    epoch = time.mktime(utc.timetuple())
    offset = datetime.fromtimestamp(epoch) - datetime.utcfromtimestamp(epoch)
    return (utc + offset).replace(tzinfo=None)


@dataclass
class LockLog:
    """A lock log entry."""

    created_at: datetime
    accessor_id: str | None
    message: str

    @staticmethod
    def request_path(device_id: str) -> str:
        return f"{Lock.device_path(device_id)}/logs"

    @classmethod
    def from_json(cls, json):
        # datetime.fromisoformat() doesn't like fractional seconds with a "Z"
        # suffix. This seems to fix it.
        created_at_str = json["createdAt"].rstrip("Z") + "+00:00"
        none_if_default = lambda x: None if x == _DEFAULT_UUID else x
        return cls(
            created_at=_utc2local(datetime.fromisoformat(created_at_str)),
            accessor_id=none_if_default(json["message"]["accessorUuid"]),
            message=LOG_EVENT_TYPES.get(json["message"]["eventCode"], "Unknown"),
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

    @staticmethod
    def request_path(device_id: str | None = None) -> str:
        """Returns the request path for a Lock."""
        path = "devices"
        if device_id:
            path = f"{path}/{device_id}"
        return path

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

    def refresh(self):
        """Refreshes the Lock state."""
        path = self.request_path(self.device_id)
        self._update_with(self._auth.request("get", path).json())

    def _toggle(self, lock_state):
        path = self.request_path(self.device_id)
        json = {"attributes": {"lockState": lock_state}}
        resp = self._auth.request("put", path, json=json)
        self._update_with(resp.json())

    def lock(self):
        """Locks the device."""
        self._toggle(1)

    def unlock(self):
        """Unlocks the device."""
        self._toggle(0)

    def logs(self, limit: int | None = None, sort_desc: bool = False) -> list[LockLog]:
        """Fetches activity logs for the lock."""
        path = LockLog.request_path(self.device_id)
        params = {}
        if limit:
            params["limit"] = limit
        if sort_desc:
            params["sort"] = "desc"
        resp = self._auth.request("get", path, params=params)
        return [LockLog.from_json(l) for l in resp.json()]

    def access_codes(self) -> list[AccessCode]:
        """Fetches access codes for this lock."""
        path = AccessCode.request_path(self.device_id)
        resp = self._auth.request("get", path)
        return [
            AccessCode.from_json(self._auth, ac, self.device_id) for ac in resp.json()
        ]

    def add_access_code(self, code: AccessCode):
        """Adds an access code to the lock."""
        if not self._auth:
            raise NotAuthenticatedError
        path = AccessCode.request_path(self.device_id)
        resp = self._auth.request("post", path, json=code.to_json())
        code._auth = self._auth
        code._update_with(resp.json(), self.device_id)
