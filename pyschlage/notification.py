"""Notifications for Schlage WiFi devices."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from . import request
from .auth import Auth
from .common import Mutable, fromisoformat, send
from .exceptions import NotAuthenticatedError

ON_ACTIVITY_ALARM = "onactalarmstate"
ON_ALARM = "onalarmstate"
ON_BATTERY_LOW = "onbatterylowstate"
ON_DEADLOCKED = "onstatedeadlocked"
ON_DOOR_CLOSED_LOCK_UNLOCKED = "ondoorclosedlockunlocked"
ON_DOOR_OPENED_LOCK_DEADLOCKED = "ondooropenedlockdeadlocked"
ON_DOOR_OPENED_LOCK_LOCKED = "ondooropenedlocklocked"
ON_LOCKED = "onstatelocked"
OFFLINE_24_HOURS = "offline24hours"
ON_UNLOCK_ACTION = "onunlockstateaction"
ON_UNLOCKED = "onstateunlocked"
UNKNOWN = "__unknown__"


def notification_fields(json: dict[str, Any]) -> dict[str, Any]:
    """Maps a notification's JSON representation onto :class:`Notification`'s
    field names.

    Every read of the cloud service's notification JSON happens here, so that
    other model layers can reuse the mapping rather than growing a second copy
    of it.

    :meta private:
    """
    return {
        "notification_id": json["notificationId"],
        "user_id": json["userId"],
        "device_id": json["deviceId"],
        "notification_type": json["notificationDefinitionId"],
        "active": json["active"],
        "filter_value": json.get("filterValue", None),
        "created_at": fromisoformat(json["createdAt"]),
        "updated_at": fromisoformat(json["updatedAt"]),
        "_json": json,
    }


def notification_to_json(
    *,
    notification_id: str,
    device_type: str | None,
    notification_type: str,
    active: bool,
    filter_value: str | None,
) -> dict[str, Any]:
    """Returns the JSON representation of a notification.

    Every write of the cloud service's notification JSON happens here, so that
    other model layers can reuse the mapping rather than growing a second copy
    of it.

    :meta private:
    """
    json: dict[str, Any] = {
        "notificationId": notification_id,
        "devicetypeId": device_type,
        "notificationDefinitionId": notification_type,
        "active": active,
    }
    if filter_value is not None:
        json["filterValue"] = filter_value
    return json


@dataclass
class Notification(Mutable):
    """A Schlage WiFi lock notification."""

    notification_id: str = ""
    """Unique identifier for the notification."""

    user_id: str | None = None
    """Unique identifier for the user this notification is scoped to."""

    device_id: str | None = None
    """Unique identifier for the device this notification is scoped to."""

    device_type: str | None = None
    """The device type of the device this notification is scoped to."""

    notification_type: str = UNKNOWN
    """The kind of event this notification fires for, e.g. :data:`ON_UNLOCK_ACTION`."""

    active: bool = False
    """Whether the notification is currently enabled."""

    filter_value: str | None = None
    """Optional value used to further scope which events trigger the notification."""

    created_at: datetime | None = None
    """The UTC time at which the notification was created."""

    updated_at: datetime | None = None
    """The UTC time at which the notification was last updated."""

    _json: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_json(cls, auth: Auth, json: dict[str, Any]) -> "Notification":
        """Creates a Notification from a JSON dict.

        :meta private:
        """
        return cls(_auth=auth, **notification_fields(json))

    def to_json(self) -> dict[str, Any]:
        """Returns a JSON dict with this Notification's mutable properties."""
        return notification_to_json(
            notification_id=self.notification_id,
            device_type=self.device_type,
            notification_type=self.notification_type,
            active=self.active,
            filter_value=self.filter_value,
        )

    def save(self):
        """Saves the Notification."""
        if not self._auth:
            raise NotAuthenticatedError
        resp = send(
            self._auth,
            request.save_notification(
                self.device_id, self.to_json(), exists=bool(self.created_at)
            ),
        )
        self._update_with(resp.json())

    def delete(self):
        """Deletes the notification."""
        if not self._auth:
            raise NotAuthenticatedError
        send(self._auth, request.delete_notification(self.notification_id))
        self._auth = None
        self._json = {}
        self.notification_id = ""
        self.active = False
