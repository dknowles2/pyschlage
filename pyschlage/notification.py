"""Notifications for Schlage WiFi devices."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .auth import Auth
from .common import Mutable, fromisoformat
from .exceptions import NotAuthenticatedError

ON_ALARM = "onalarmstate"
ON_BATTERY_LOW = "onbatterylowstate"
ON_LOCKED = "onstatelocked"
OFFLINE_24_HOURS = "offline24hours"
ON_UNLOCK_ACTION = "onunlockstateaction"
ON_UNLOCKED = "onstateunlocked"
UNKNOWN = "__unknown__"


@dataclass
class Notification(Mutable):
    """A Schlage WiFi lock notification."""

    notification_id: str = ""
    user_id: str | None = None
    device_id: str | None = None
    device_type: str | None = None
    notification_type: str = UNKNOWN
    active: bool = False
    filter_value: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    _json: dict[str, Any] = field(default_factory=dict, repr=False)

    @staticmethod
    def request_path(notification_id: str | None = None) -> str:
        """Returns the request path for the Notification.

        :meta private:
        """
        path = "notifications"
        if notification_id is not None:
            path = f"{path}/{notification_id}"
        return path

    @classmethod
    def from_json(cls, auth: Auth, json: dict[str, Any]) -> "Notification":
        return Notification(
            _auth=auth,
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
        """Returns a JSON dict with this Notification's mutable properties."""
        json: dict[str, Any] = {
            "notificationId": self.notification_id,
            "userId": self.user_id,
            "deviceId": self.device_id,
            "devicetypeId": self.device_type,
            "notificationDefinitionId": self.notification_type,
            "active": self.active,
        }
        if self.filter_value is not None:
            json["filterValue"] = self.filter_value
        return json

    def save(self):
        """Saves the Notification."""
        if not self._auth:
            raise NotAuthenticatedError
        method = "put" if self.created_at else "post"
        path = self.request_path(self.notification_id)
        resp = self._auth.request(method, path, self.to_json())
        self._update_with(resp.json())

    def delete(self):
        """Deletes the notification."""
        if not self._auth:
            raise NotAuthenticatedError
        path = self.request_path(self.notification_id)
        self._auth.request("delete", path)
        self._auth = None
        self._json = {}
        self.notification_id = None
        self.active = False
