"""Objects and routines related to Schlage WiFi access codes."""

from __future__ import annotations

from dataclasses import astuple, dataclass, field
from datetime import UTC, datetime
from typing import Any

from .notification import Notification

_MIN_TIME = 0
_MAX_TIME = 0xFFFFFFFF
_MIN_HOUR = 0
_MIN_MINUTE = 0
_MAX_HOUR = 23
_MAX_MINUTE = 59
_ALL_DAYS = "7F"


@dataclass(frozen=True, slots=True)
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
    def from_str(cls, s: str) -> DaysOfWeek:
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
        return f"{n:02X}"


@dataclass(frozen=True, slots=True)
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

        Returns None for a schedule that spans the whole week, since that is
        equivalent to having no schedule at all.

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

    def to_json(self) -> dict[str, Any]:
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


@dataclass(frozen=True, slots=True)
class MultiRecurringSchedule:
    """A schedule consisting of at most two recurring schedules."""

    schedule1: RecurringSchedule | None
    """The first recurring schedule during which the access code is enabled."""

    schedule2: RecurringSchedule | None
    """The second recurring schedule during which the access code is enabled.

    May only be set if ``schedule1`` is also set.
    """

    def __post_init__(self):
        if self.schedule1 is None and self.schedule2 is not None:
            raise ValueError("schedule1 must be set for schedule2 to be settable.")


@dataclass(frozen=True, slots=True)
class TemporarySchedule:
    """A temporary schedule for when an AccessCode is enabled."""

    start: datetime
    """The time at which the schedule should start."""

    end: datetime
    """The time at which the schedule should end."""

    @classmethod
    def from_json(cls, json: dict[str, Any]) -> TemporarySchedule:
        """Creates a TemporarySchedule from a JSON dict.

        :meta private:
        """
        return cls(
            start=datetime.fromtimestamp(json["activationSecs"], tz=UTC),
            end=datetime.fromtimestamp(json["expirationSecs"], tz=UTC),
        )

    def to_json(self) -> dict[str, Any]:
        """Returns a JSON dict of this TemporarySchedule.

        :meta private:
        """
        return {
            "activationSecs": int(self.start.timestamp()),
            "expirationSecs": int(self.end.timestamp()),
        }


#: Any of the schedule kinds an access code may carry.
Schedule = MultiRecurringSchedule | TemporarySchedule | RecurringSchedule


def _to_json(
    *,
    name: str,
    code: str,
    schedule: Schedule | None,
    notify_on_use: bool,
    disabled: bool,
) -> dict[str, Any]:
    """Builds the wire representation shared by new and existing access codes."""
    json: dict[str, Any] = {
        "friendlyName": name,
        "accessCode": int(code),
        "accessCodeLength": len(code),
        "notificationEnabled": int(notify_on_use),
        "disabled": int(disabled),
        "activationSecs": _MIN_TIME,
        "expirationSecs": _MAX_TIME,
        "schedule1": RecurringSchedule().to_json(),
    }
    if isinstance(schedule, MultiRecurringSchedule):
        if schedule.schedule1 is not None:
            json["schedule1"] = schedule.schedule1.to_json()
        if schedule.schedule2 is not None:
            json["schedule2"] = schedule.schedule2.to_json()
    elif isinstance(schedule, RecurringSchedule):
        json["schedule1"] = schedule.to_json()
    elif schedule is not None:
        json.update(schedule.to_json())
    return json


@dataclass(frozen=True, slots=True)
class NewAccessCode:
    """An access code that has not yet been added to a lock.

    Pass one of these to :meth:`pyschlage.Schlage.add_access_code`, which
    returns the resulting :class:`AccessCode`.
    """

    name: str
    """User-specified name for the access code."""

    code: str
    """The access code."""

    schedule: Schedule | None = None
    """Optional schedule at which the code is enabled."""

    notify_on_use: bool = False
    """Whether to notify the user's phone app when the code is used."""

    disabled: bool = False
    """Whether the code is disabled."""

    def to_json(self) -> dict[str, Any]:
        """Returns a JSON dict for this access code.

        :meta private:
        """
        return _to_json(
            name=self.name,
            code=self.code,
            schedule=self.schedule,
            notify_on_use=self.notify_on_use,
            disabled=self.disabled,
        )


@dataclass(frozen=True, slots=True)
class AccessCode:
    """An access code that exists on a lock.

    This is immutable. To change one, build a modified copy with
    :func:`dataclasses.replace` and pass it to
    :meth:`pyschlage.Schlage.update_access_code`.
    """

    access_code_id: str
    """Unique identifier for the access code."""

    device_id: str
    """Unique identifier for the device the access code belongs to."""

    device_type: str = ""
    """The device type of the lock the access code belongs to."""

    name: str = ""
    """User-specified name for the access code."""

    code: str = ""
    """The access code."""

    schedule: Schedule | None = None
    """Optional schedule at which the code is enabled."""

    notify_on_use: bool = False
    """Whether to notify the user's phone app when the code is used."""

    disabled: bool = False
    """Whether the code is disabled."""

    _notification: Notification | None = field(default=None, repr=False, compare=False)
    """The notification that fires when this code is used, if one exists.

    Tracked so that updates know whether to create or modify it.
    """

    _json: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @staticmethod
    def request_path(device_id: str, access_code_id: str | None = None) -> str:
        """Returns the request path for an AccessCode.

        :meta private:
        """
        path = f"devices/{device_id}/storage/accesscode"
        if access_code_id:
            return f"{path}/{access_code_id}"
        return path

    @classmethod
    def from_json(
        cls,
        json: dict[str, Any],
        *,
        device_id: str,
        device_type: str = "",
        notification: Notification | None = None,
    ) -> AccessCode:
        """Creates an AccessCode from a JSON dict.

        :meta private:
        """
        schedule: Schedule | None = None
        if json["activationSecs"] == _MIN_TIME and json["expirationSecs"] == _MAX_TIME:
            if "schedule2" in json:
                schedule = MultiRecurringSchedule(
                    RecurringSchedule.from_json(json["schedule1"]),
                    RecurringSchedule.from_json(json["schedule2"]),
                )
            else:
                schedule = RecurringSchedule.from_json(json["schedule1"])
        else:
            schedule = TemporarySchedule.from_json(json)

        access_code_length = json.get("accessCodeLength", 4)
        return cls(
            _json=json,
            _notification=notification,
            access_code_id=json["accesscodeId"],
            device_id=device_id,
            device_type=device_type,
            name=json["friendlyName"],
            code=f"{json['accessCode']:0{access_code_length}}",
            disabled=bool(json.get("disabled", None)),
            schedule=schedule,
            notify_on_use=notification is not None and notification.active,
        )

    def to_json(self) -> dict[str, Any]:
        """Returns a JSON dict for this access code.

        :meta private:
        """
        json = _to_json(
            name=self.name,
            code=self.code,
            schedule=self.schedule,
            notify_on_use=self.notify_on_use,
            disabled=self.disabled,
        )
        json["accesscodeId"] = self.access_code_id
        return json
