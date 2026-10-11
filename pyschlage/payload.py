"""Shapes of the JSON the Schlage WiFi cloud service returns.

These describe the service's responses as the library actually reads them, so
that mypy checks the key names and value types the parsing routines rely on.
They are documentation of a reverse-engineered API, not validation: the
service is free to send something else, and the ``cast`` each ``from_json()``
performs is where that risk is taken.

A key is required here only where the parsing code indexes it without
guarding; everything the code reads with :meth:`dict.get` or behind an ``in``
check is :data:`~typing.NotRequired`.

:meta private:
"""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict


class UserJson(TypedDict):
    """A user, as returned by ``GET /users`` or nested in a lock.

    :meta private:
    """

    email: str
    identityId: str
    friendlyName: NotRequired[str | None]


class LockStateMetadataJson(TypedDict):
    """The ``lockStateMetadata`` attribute of a lock.

    :meta private:
    """

    actionType: str
    UUID: str | None
    name: str | None


class LockAttributesJson(TypedDict, total=False):
    """The ``attributes`` map of a lock.

    The service reports a different subset of these per model and per
    connectivity state, so none of them are required.

    :meta private:
    """

    lockState: int
    lockStateMetadata: dict[str, Any]
    batteryLevel: int
    beeperEnabled: int
    lockAndLeaveEnabled: int
    autoLockTime: int
    mainFirmwareVersion: str
    bleFirmwareVersion: str
    wifiFirmwareVersion: str
    keypadFirmwareVersion: str
    macAddress: str
    deviceUid: str
    serialNumber: str
    manufacturerName: str
    accessCodeLength: int
    maxUserCodes: int
    batteryLowState: int
    doorState: int
    alarmSelection: int
    alarmSensitivity: int
    opMode: int
    SAT: str


class LockJson(TypedDict):
    """A lock, as returned by ``GET /devices``.

    :meta private:
    """

    deviceId: str
    name: str
    devicetypeId: str
    attributes: LockAttributesJson
    modelName: NotRequired[str]
    connected: NotRequired[bool]
    users: NotRequired[list[dict[str, Any]]]
    CAT: NotRequired[str]
    SAT: NotRequired[str]


class RecurringScheduleJson(TypedDict, total=False):
    """A recurring schedule of an access code.

    The service sends an empty map for an access code with no schedule, so
    none of these are required.

    :meta private:
    """

    daysOfWeek: str
    startHour: int
    startMinute: int
    endHour: int
    endMinute: int


class AccessCodeJson(TypedDict):
    """An access code, as returned by ``GET /devices/{id}/storage/accesscode``.

    :meta private:
    """

    accesscodeId: str
    friendlyName: str
    accessCode: int
    activationSecs: int
    expirationSecs: int
    schedule1: RecurringScheduleJson | None
    schedule2: NotRequired[RecurringScheduleJson | None]
    accessCodeLength: NotRequired[int]
    disabled: NotRequired[int | None]


class LogMessageJson(TypedDict):
    """The ``message`` object of a log entry.

    :meta private:
    """

    eventCode: int
    accessorUuid: str
    keypadUuid: str


class LogJson(TypedDict):
    """A log entry, as returned by ``GET /devices/{id}/logs``.

    ``message`` is the bare string ``"RESET_LOGS"`` rather than an object when
    the lock's history was cleared.

    :meta private:
    """

    createdAt: str
    message: NotRequired[dict[str, Any] | str]


class NotificationJson(TypedDict):
    """A notification, as returned by ``GET /notifications``.

    :meta private:
    """

    notificationId: str
    userId: str
    deviceId: str
    notificationDefinitionId: str
    active: bool
    createdAt: str
    updatedAt: str
    filterValue: NotRequired[str | None]
