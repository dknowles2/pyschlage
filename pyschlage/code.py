"""Objects and routines related to Schlage WiFI access codes."""

from __future__ import annotations

from dataclasses import astuple, dataclass, field
from datetime import datetime
from typing import Any

from .auth import Auth
from .common import Mutable
from .device import Device
from .exceptions import NotAuthenticatedError
from .notification import ON_UNLOCK_ACTION, Notification

_MIN_TIME = 0
_MAX_TIME = 0xFFFFFFFF
_MIN_HOUR = 0
_MIN_MINUTE = 0
_MAX_HOUR = 23
_MAX_MINUTE = 59
_ALL_DAYS = "7F"


@dataclass
class TemporarySchedule:
    """A temporary schedule for when an AccessCode is enabled."""

    start: datetime
    """The time at which the schedule should start."""

    end: datetime
    """The time at which the schedule should end."""

    @classmethod
    def from_json(cls, json) -> TemporarySchedule:
        """Creates a TemporarySchedule from a JSON dict.

        :meta private:
        """
        return TemporarySchedule(
            start=datetime.fromtimestamp(json["activationSecs"]),
            end=datetime.fromtimestamp(json["expirationSecs"]),
        )

    def to_json(self) -> dict:
        """Returns a JSON dict of this TemporarySchedule.

        :meta private:
        """
        return {
            "activationSecs": int(self.start.timestamp()),
            "expirationSecs": int(self.end.timestamp()),
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
        """Creates a DaysOfWeek from a hex string.

        :meta private:
        """
        n = int(s, 16)
        return cls(*[(n & (1 << i)) != 0 for i in reversed(range(7))])

    def to_str(self) -> str:
        """Returns the string representation.

        :meta private:
        """
        n = 0
        for d in astuple(self):
            n = (n << 1) | d
        return hex(n).lstrip("0x").upper()


@dataclass
class RecurringSchedule:
    """A recurring schedule for when an AccessCode is enabled."""

    days_of_week: DaysOfWeek = field(default_factory=DaysOfWeek)
    """Days of the week on which the access code is enabled."""

    start_hour: int = _MIN_HOUR
    """Hour at which the access code is enabled."""

    start_minute: int = _MIN_MINUTE
    """Minute at which the access code is enabled."""

    end_hour: int = _MAX_HOUR
    """Hour at which the access code is disabled."""

    end_minute: int = _MAX_MINUTE
    """Minute at which the access code is disabled."""

    @classmethod
    def from_json(cls, json: dict[str, Any] | None) -> RecurringSchedule | None:
        """Creates a RecurringSchedule from a JSON dict.

        :meta private:
        """
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
        """Returns a JSON dict of this RecurringSchedule.

        :meta private:
        """
        return {
            "daysOfWeek": self.days_of_week.to_str(),
            "startHour": self.start_hour,
            "startMinute": self.start_minute,
            "endHour": self.end_hour,
            "endMinute": self.end_minute,
        }


@dataclass
class AccessCode(Mutable):
    """An access code for a lock."""

    name: str = ""
    """User-specified name for the access code."""

    code: str = ""
    """The access code."""

    schedule: TemporarySchedule | RecurringSchedule | None = None
    """Optional schedule at which the code is enabled."""

    notify_on_use: bool = False
    """Whether to notify the user's phone app when the code is used."""

    disabled: bool = False
    """Whether the code is disabled."""

    device_id: str | None = field(default=None, repr=False)
    """Unique identifier for the device the access code is associated with."""

    access_code_id: str | None = field(default=None, repr=False)
    """Unique identifier for the access code."""

    _device: Device | None = field(default=None, repr=False)
    _notification: Notification | None = field(default=None, repr=False)
    _json: dict[Any, Any] = field(default_factory=dict, repr=False)

    @staticmethod
    def request_path(device_id: str, access_code_id: str | None = None) -> str:
        """Returns the request path for an AccessCode.

        :meta private:
        """
        path = f"devices/{device_id}/storage/accesscode"
        if access_code_id:
            return f"{path}/{access_code_id}"  # pragma: no cover
        return path

    @classmethod
    def from_json(cls, auth: Auth, device: Device, json: dict[str, Any]) -> AccessCode:
        """Creates an AccessCode from a JSON dict.

        :meta private:
        """
        schedule: TemporarySchedule | RecurringSchedule | None = None
        if json["activationSecs"] == _MIN_TIME and json["expirationSecs"] == _MAX_TIME:
            schedule = RecurringSchedule.from_json(json["schedule1"])
        else:
            schedule = TemporarySchedule.from_json(json)

        access_code_length = json.get("accessCodeLength", 4)
        return AccessCode(
            _auth=auth,
            _json=json,
            _device=device,
            access_code_id=json["accesscodeId"],
            name=json["friendlyName"],
            code=f"{json['accessCode']:0{access_code_length}}",
            notify_on_use=bool(json["notification"]),
            disabled=bool(json.get("disabled", None)),
            schedule=schedule,
            device_id=device.device_id,
        )

    def to_json(self) -> dict:
        """Returns a JSON dict with this AccessCode's mutable properties.

        :meta private:
        """
        json = {
            "friendlyName": self.name,
            "accessCode": int(self.code),
            "accessCodeLength": len(self.code),
            "notification": int(self.notify_on_use),
            "notificationEnabled": self.notify_on_use,
            "disabled": int(self.disabled),
            "activationSecs": _MIN_TIME,
            "expirationSecs": _MAX_TIME,
            "schedule1": RecurringSchedule().to_json(),
        }
        if self.access_code_id:
            json["accesscodeId"] = self.access_code_id
        if isinstance(self.schedule, RecurringSchedule):
            json["schedule1"] = self.schedule.to_json()
        elif self.schedule is not None:
            json.update(self.schedule.to_json())

        return json

    def save(self):
        """Commits changes to the access code.

        :raise pyschlage.exceptions.NotAuthenticatedError: When the user is not
            authenticated.
        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        if not self._auth:
            raise NotAuthenticatedError
        assert self._device is not None

        command = "updateaccesscode" if self.access_code_id else "addaccesscode"
        resp = self._device.send_command(command, self.to_json())

        # NOTE: We don't call self._update_with() here because the API only returns
        # the accesscodeId field.
        resp_json = resp.json()
        if "accesscodeId" in resp_json:
            self.access_code_id = resp_json["accesscodeId"]

        self.device_id = self._device.device_id
        if self._notification is None:
            self._notification = Notification(
                _auth=self._auth,
                notification_id=f"{self._auth.user_id}_{self.access_code_id}",
                user_id=self._auth.user_id,
                device_id=self.device_id,
                device_type=self._device.device_type,
                notification_type=ON_UNLOCK_ACTION,
            )
        self._notification.filter_value = self.name
        self._notification.active = self.notify_on_use
        self._notification.save()

    def delete(self):
        """Deletes the access code.

        :raise pyschlage.exceptions.NotAuthenticatedError: When the user is not
            authenticated.
        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        if self._auth is None:
            raise NotAuthenticatedError
        assert self._device is not None
        self._device.send_command("deleteaccesscode", self.to_json())
        if self._notification is not None:
            self._notification.delete()
        self._auth = None
        self._json = {}
        self._device = None
        self._notification = None
        self.access_code_id = None
        self.disabled = True
