"""Immutable snapshots of Schlage WiFi lock notifications."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, cast

from .. import payload
from ..notification import UNKNOWN, notification_fields, notification_to_json


@dataclass(frozen=True, slots=True)
class Notification:
    """A Schlage WiFi lock notification.

    This is an immutable snapshot of the notification as it was last fetched.
    """

    notification_id: str = ""
    """Unique identifier for the notification."""

    user_id: str | None = None
    """Unique identifier for the user this notification is scoped to."""

    device_id: str | None = None
    """Unique identifier for the device this notification is scoped to."""

    device_type: str | None = None
    """The device type of the device this notification is scoped to."""

    notification_type: str = UNKNOWN
    """The kind of event this notification fires for.

    See :data:`pyschlage.notification.ON_UNLOCK_ACTION` and its neighbours for
    the known values.
    """

    active: bool = False
    """Whether the notification is currently enabled."""

    filter_value: str | None = None
    """Optional value used to further scope which events trigger the notification."""

    created_at: datetime | None = None
    """The UTC time at which the notification was created."""

    updated_at: datetime | None = None
    """The UTC time at which the notification was last updated."""

    _json: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_json(cls, json: dict[str, Any]) -> Notification:
        """Creates a Notification from a JSON dict.

        :meta private:
        """
        return cls(
            _json=json, **notification_fields(cast(payload.NotificationJson, json))
        )

    def to_json(self) -> dict[str, Any]:
        """Returns a JSON dict with this Notification's mutable properties.

        :meta private:
        """
        return notification_to_json(
            notification_id=self.notification_id,
            device_type=self.device_type,
            notification_type=self.notification_type,
            active=self.active,
            filter_value=self.filter_value,
        )
