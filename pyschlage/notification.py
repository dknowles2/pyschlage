"""Notifications for Schlage WiFi devices."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .common import fromisoformat

ON_ALARM = "onalarmstate"
ON_BATTERY_LOW = "onbatterylowstate"
ON_LOCKED = "onstatelocked"
OFFLINE_24_HOURS = "offline24hours"
ON_UNLOCK_ACTION = "onunlockstateaction"
ON_UNLOCKED = "onstateunlocked"
UNKNOWN = "__unknown__"


@dataclass(frozen=True, slots=True)
class Notification:
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

    _json: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @staticmethod
    def request_path(notification_id: str | None = None) -> str:
        """Returns the request path for the Notification.

        :meta private:
        """
        path = "notifications"
        if notification_id is not None:
            path = f"{path}/{notification_id}"
        return path

    @staticmethod
    def id_for_access_code(user_id: str, access_code_id: str) -> str:
        """Returns the notification id used for an access code's notification.

        The cloud service has no direct link between an access code and the
        notification that fires when it is used; the two are associated purely
        by this id convention.

        :meta private:
        """
        return f"{user_id}_{access_code_id}"

    @classmethod
    def from_json(cls, json: dict[str, Any]) -> Notification:
        """Creates a Notification from a JSON dict.

        :meta private:
        """
        return cls(
            _json=json,
            notification_id=json["notificationId"],
            user_id=json["userId"],
            device_id=json["deviceId"],
            notification_type=json["notificationDefinitionId"],
            active=json["active"],
            filter_value=json.get("filterValue", None),
            created_at=fromisoformat(json["createdAt"]),
            updated_at=fromisoformat(json["updatedAt"]),
        )

    def to_json(self) -> dict[str, Any]:
        """Returns a JSON dict with this Notification's mutable properties.

        :meta private:
        """
        json: dict[str, Any] = {
            "notificationId": self.notification_id,
            "devicetypeId": self.device_type,
            "notificationDefinitionId": self.notification_type,
            "active": self.active,
        }
        if self.filter_value is not None:
            json["filterValue"] = self.filter_value
        return json
