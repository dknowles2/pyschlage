"""Immutable snapshots of Schlage WiFi access codes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

from .. import payload
from ..code import (
    MultiRecurringSchedule,
    RecurringSchedule,
    TemporarySchedule,
    access_code_fields,
    access_code_to_json,
)
from .notification import Notification


@dataclass(frozen=True, slots=True)
class NewAccessCode:
    """An access code to be added to a lock.

    This is distinct from :class:`AccessCode`, which is a snapshot of a code
    the lock already has.
    """

    name: str = ""
    """User-specified name for the access code."""

    code: str = ""
    """The access code."""

    schedule: MultiRecurringSchedule | TemporarySchedule | RecurringSchedule | None = (
        None
    )
    """Optional schedule at which the code is enabled."""

    notify_on_use: bool = False
    """Whether to notify the user's phone app when the code is used."""

    disabled: bool = False
    """Whether the code is disabled."""

    def to_json(self) -> dict[str, Any]:
        """Returns a JSON dict with this access code's properties.

        :meta private:
        """
        return access_code_to_json(
            name=self.name,
            code=self.code,
            schedule=self.schedule,
            notify_on_use=self.notify_on_use,
            disabled=self.disabled,
        )


@dataclass(frozen=True, slots=True)
class AccessCode:
    """An access code for a lock.

    This is an immutable snapshot of the code as it was last fetched. Build a
    modified copy with :func:`dataclasses.replace` and commit it with
    :meth:`pyschlage.aio.Schlage.update_access_code`.
    """

    access_code_id: str
    """Unique identifier for the access code."""

    device_id: str
    """Unique identifier for the device the access code is associated with."""

    device_type: str
    """The device type of the lock the access code is associated with."""

    name: str = ""
    """User-specified name for the access code."""

    code: str = ""
    """The access code."""

    schedule: MultiRecurringSchedule | TemporarySchedule | RecurringSchedule | None = (
        None
    )
    """Optional schedule at which the code is enabled."""

    notify_on_use: bool = False
    """Whether to notify the user's phone app when the code is used."""

    disabled: bool = False
    """Whether the code is disabled."""

    _notification: Notification | None = field(default=None, repr=False, compare=False)

    _json: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_json(
        cls,
        json: dict[str, Any],
        *,
        device_id: str,
        device_type: str,
        notification: Notification | None = None,
    ) -> AccessCode:
        """Creates an AccessCode from a JSON dict.

        :meta private:
        """
        return cls(
            device_type=device_type,
            _notification=notification,
            _json=json,
            **access_code_fields(
                cast(payload.AccessCodeJson, json),
                device_id=device_id,
                notify_on_use=notification is not None and notification.active,
            ),
        )

    def to_json(self) -> dict[str, Any]:
        """Returns a JSON dict with this access code's properties.

        :meta private:
        """
        return access_code_to_json(
            name=self.name,
            code=self.code,
            schedule=self.schedule,
            notify_on_use=self.notify_on_use,
            disabled=self.disabled,
            access_code_id=self.access_code_id,
        )
