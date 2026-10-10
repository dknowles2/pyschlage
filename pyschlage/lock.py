"""Lock object used for Schlage WiFi devices."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import IntEnum
import re
from typing import Any, TypedDict, TypeVar, cast

from . import payload, request
from .auth import Auth
from .code import AccessCode
from .common import redact, send
from .device import (
    WIFI_DEVICE_TYPES,
    AlarmMode,
    BatteryState,
    Device,
    DoorState,
    OperatingMode,
)
from .exceptions import NotAuthenticatedError
from .log import KEYPAD_DISABLED_INVALID_CODE, LockLog
from .notification import ON_UNLOCK_ACTION, Notification
from .user import User

AUTO_LOCK_TIMES = (0, 5, 15, 30, 60, 120, 240, 300, 360, 600, 900, 1800)

# Values reported in the lockState attribute. Not all locks report all of
# these: MOTOR_JAMMED, PASSAGE_MODE and DEADLOCKED are only reported by
# newer models.
_LOCK_STATE_UNLOCKED = 0
_LOCK_STATE_LOCKED = 1
_LOCK_STATE_JAMMED = 2
_LOCK_STATE_MOTOR_JAMMED = 4
_LOCK_STATE_PASSAGE_MODE = 5
_LOCK_STATE_DEADLOCKED = 6

_LOCKED_STATES = (_LOCK_STATE_LOCKED, _LOCK_STATE_DEADLOCKED)
_UNLOCKED_STATES = (_LOCK_STATE_UNLOCKED, _LOCK_STATE_PASSAGE_MODE)
_JAMMED_STATES = (_LOCK_STATE_JAMMED, _LOCK_STATE_MOTOR_JAMMED)


@dataclass
class LockStateMetadata:
    """Metadata about the current lock state."""

    action_type: str
    """The action type that last changed the lock state."""

    uuid: str | None = None
    """The UUID of the actor that changed the lock state."""

    name: str | None = None
    """Human readable name of the access code that changed the lock state.

    If the lock state was not changed by an access code, this will be None.
    """

    @classmethod
    def from_json(cls, json: dict[str, Any]) -> LockStateMetadata:
        """Creates a LockStateMetadata from a JSON object.

        :meta private:
        """
        metadata_json = cast(payload.LockStateMetadataJson, json)
        return cls(
            action_type=metadata_json["actionType"],
            uuid=metadata_json["UUID"],
            name=metadata_json["name"],
        )


# Keys of a lock's raw JSON that are safe to report in diagnostics. Everything
# else is redacted.
_DIAGNOSTICS_ALLOWED = [
    "attributes.accessCodeLength",
    "attributes.actAlarmBuzzerEnabled",
    "attributes.actAlarmState",
    "attributes.adminOnlyEnabled",
    "attributes.actuationCurrentMax",
    "attributes.alarmSelection",
    "attributes.alarmSensitivity",
    "attributes.alarmState",
    "attributes.autoLockTime",
    "attributes.batteryChangeDate",
    "attributes.batteryLevel",
    "attributes.batteryLowState",
    "attributes.batterySaverConfig",
    "attributes.batterySaverState",
    "attributes.beeperEnabled",
    "attributes.bleFirmwareVersion",
    "attributes.doorState",
    "attributes.firmwareUpdate",
    "attributes.hardwareVersion",
    "attributes.homePosCurrentMax",
    "attributes.keypadFirmwareVersion",
    "attributes.lastTalkedTime",
    "attributes.lockAndLeaveEnabled",
    "attributes.lockState",
    "attributes.lockStateMetadata.actionType",
    "attributes.mainFirmwareVersion",
    "attributes.manufacturerName",
    "attributes.maxSchedule",
    "attributes.maxUserCodes",
    "attributes.mode",
    "attributes.modelName",
    "attributes.opMode",
    "attributes.periodicDeepQueryTimeSetting",
    "attributes.profileVersion",
    "attributes.psPollEnabled",
    "attributes.supportedFeatures.activityAlarm",
    "attributes.supportedFeatures.scheduledLocking",
    "attributes.supportedFeatures.vlac",
    "attributes.supportedFeatures.wifiUpdateCommand",
    "attributes.timezone",
    "attributes.wifiFirmwareVersion",
    "attributes.wifiRssi",
    "connected",
    "connectivityUpdated",
    "created",
    "devicetypeId",
    "lastUpdated",
    "modelName",
    "name",
    "role",
    "timezone",
]


def lock_diagnostics(json: dict[str, Any]) -> dict[Any, Any]:
    """Returns a redacted copy of a lock's raw JSON, for diagnostics purposes.

    :meta private:
    """
    return redact(json, allowed=_DIAGNOSTICS_ALLOWED)


class LockFields(TypedDict):
    """The fields of a lock parsed out of its JSON representation.

    Splatting this into a model's constructor is checked, so a model that
    consumes :func:`lock_fields` has to accept exactly these fields with these
    types.

    :meta private:
    """

    device_id: str
    name: str
    model_name: str
    device_type: str
    connected: bool
    battery_level: int | None
    is_locked: bool | None
    is_jammed: bool | None
    lock_state_metadata: LockStateMetadata | None
    beeper_enabled: bool
    lock_and_leave_enabled: bool
    auto_lock_time: int
    firmware_version: str | None
    ble_firmware_version: str | None
    wifi_firmware_version: str | None
    keypad_firmware_version: str | None
    mac_address: str | None
    serial_number: str | None
    manufacturer_name: str | None
    access_code_length: int | None
    max_user_codes: int | None
    battery_low_state: BatteryState | None
    door_state: DoorState | None
    alarm_mode: AlarmMode | None
    alarm_sensitivity: int | None
    operating_mode: OperatingMode | None
    users: dict[str, User]
    _cat: str


_E = TypeVar("_E", bound=IntEnum)


def _enum_or_none(enum: type[_E], value: int | None) -> _E | None:
    """Returns the enum member for a reported value, or None if absent."""
    return None if value is None else enum(value)


def lock_fields(json: payload.LockJson) -> LockFields:
    """Maps a lock's JSON representation onto :class:`Lock`'s field names.

    Every read of the cloud service's lock JSON happens here, so that other
    model layers can reuse the mapping rather than growing a second copy of it.

    :meta private:
    """
    attributes = json["attributes"]

    is_locked = is_jammed = None
    lock_state = attributes.get("lockState")
    if lock_state in _LOCKED_STATES + _UNLOCKED_STATES + _JAMMED_STATES:
        is_locked = lock_state in _LOCKED_STATES
        is_jammed = lock_state in _JAMMED_STATES

    lock_state_metadata = None
    if "lockStateMetadata" in attributes:
        lock_state_metadata = LockStateMetadata.from_json(
            attributes["lockStateMetadata"]
        )

    users: dict[str, User] = {}
    for user_json in json.get("users", []):
        user = User.from_json(user_json)
        users[user.user_id] = user

    return {
        "device_id": json["deviceId"],
        "name": json["name"],
        "model_name": json.get("modelName", ""),
        "device_type": json["devicetypeId"],
        "connected": json.get("connected", False),
        "battery_level": attributes.get("batteryLevel"),
        "is_locked": is_locked,
        "is_jammed": is_jammed,
        "lock_state_metadata": lock_state_metadata,
        "beeper_enabled": attributes.get("beeperEnabled") == 1,
        "lock_and_leave_enabled": attributes.get("lockAndLeaveEnabled") == 1,
        "auto_lock_time": attributes.get("autoLockTime", 0),
        "firmware_version": attributes.get("mainFirmwareVersion"),
        "ble_firmware_version": attributes.get("bleFirmwareVersion"),
        "wifi_firmware_version": attributes.get("wifiFirmwareVersion"),
        "keypad_firmware_version": attributes.get("keypadFirmwareVersion"),
        "mac_address": attributes.get("macAddress"),
        "serial_number": attributes.get("serialNumber"),
        "manufacturer_name": attributes.get("manufacturerName"),
        "access_code_length": attributes.get("accessCodeLength"),
        "max_user_codes": attributes.get("maxUserCodes"),
        "battery_low_state": _enum_or_none(
            BatteryState, attributes.get("batteryLowState")
        ),
        "door_state": _enum_or_none(DoorState, attributes.get("doorState")),
        "alarm_mode": _enum_or_none(AlarmMode, attributes.get("alarmSelection")),
        "alarm_sensitivity": attributes.get("alarmSensitivity"),
        "operating_mode": _enum_or_none(OperatingMode, attributes.get("opMode")),
        "_cat": json.get("CAT", ""),
        "users": users,
    }


def determine_last_changed_by(
    metadata: LockStateMetadata | None, users: dict[str, User]
) -> str | None:
    """Determines the last entity or user that changed a lock's state.

    :meta private:
    """
    if metadata is None:
        return None

    user_suffix = ""
    if metadata.uuid is not None and (user := users.get(metadata.uuid)):
        user_suffix = f" - {user.name}"

    match metadata.action_type:
        case "thumbTurn":
            return "thumbturn"
        case "1touchLocking":
            return "1-touch locking"
        case "accesscode":
            return f"keypad - {metadata.name}"
        case "AppleHomeNFC":
            return f"apple nfc device{user_suffix}"
        case "virtualKey":
            return f"mobile device{user_suffix}"
    return "unknown"


def is_keypad_disabled(logs: list[LockLog]) -> bool:
    """Returns whether the newest of the given logs reports a disabled keypad.

    :meta private:
    """
    if not logs:
        return False
    newest_log = max(logs, key=lambda log: log.created_at)
    return newest_log.event_code == KEYPAD_DISABLED_INVALID_CODE


@dataclass
class Lock(Device):
    """A Schlage WiFi lock."""

    name: str = ""
    """User-specified name of the lock."""

    model_name: str = ""
    """The model name of the lock."""

    connected: bool = False
    """Whether the lock is connected to WiFi."""

    battery_level: int | None = None
    """The remaining battery level of the lock.

    This is an integer between 0 and 100 or None if lock is unavailable.
    """

    is_locked: bool | None = False
    """Whether the device is currently locked or None if lock is unavailable.

    Locks that support deadlocking report True while deadlocked. Locks in
    passage mode report False.
    """

    is_jammed: bool | None = False
    """Whether the lock has identified itself as jammed.

    This is True for both a jammed bolt and a jammed motor. Returns None if
    lock is unavailable.
    """

    lock_state_metadata: LockStateMetadata | None = None
    """Metadata about the current lock state."""

    beeper_enabled: bool = False
    """Whether the keypress beep is enabled."""

    lock_and_leave_enabled: bool = False
    """Whether lock-and-leave (a.k.a. "1-Touch Locking) feature is enabled."""

    auto_lock_time: int = 0
    """Time (in seconds) after which the lock will automatically lock itself."""

    firmware_version: str | None = None
    """The firmware version installed on the lock or None if lock is unavailable."""

    ble_firmware_version: str | None = None
    """The firmware version of the lock's Bluetooth radio."""

    wifi_firmware_version: str | None = None
    """The firmware version of the lock's WiFi radio.

    This is None for locks without a WiFi radio.
    """

    keypad_firmware_version: str | None = None
    """The firmware version of the lock's keypad."""

    mac_address: str | None = None
    """The MAC address for the lock or None if lock is unavailable."""

    serial_number: str | None = None
    """The serial number of the lock."""

    manufacturer_name: str | None = None
    """The manufacturer name reported by the lock."""

    access_code_length: int | None = None
    """The number of digits in this lock's access codes."""

    max_user_codes: int | None = None
    """The maximum number of access codes this lock can store."""

    battery_low_state: BatteryState | None = None
    """The coarse battery state reported by the lock.

    This is independent of :attr:`battery_level`; locks may report a low
    battery before the level drops appreciably.
    """

    door_state: DoorState | None = None
    """The state of the door, for locks with a door position sensor.

    This is None for locks without one.
    """

    alarm_mode: AlarmMode | None = None
    """The event the lock's built-in alarm triggers on."""

    alarm_sensitivity: int | None = None
    """The sensitivity of the lock's built-in alarm."""

    operating_mode: OperatingMode | None = None
    """Which protocol stack the lock is operating under."""

    users: dict[str, User] = field(default_factory=dict)
    """Users with access to this lock, keyed by their ID."""

    access_codes: dict[str, AccessCode] | None = None
    """Access codes for this lock, keyed by their ID."""

    _cat: str = field(default="", repr=False)

    _json: dict[Any, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_json(cls, auth: Auth, json: dict[str, Any]) -> Lock:
        """Creates a Lock from a JSON object.

        :meta private:
        """
        return cls(_auth=auth, _json=json, **lock_fields(cast(payload.LockJson, json)))

    def get_diagnostics(self) -> dict[Any, Any]:
        """Returns a redacted dict of the raw JSON for diagnostics purposes."""
        return lock_diagnostics(self._json)

    def _is_wifi_lock(self) -> bool:
        return any(self.device_type.startswith(p) for p in WIFI_DEVICE_TYPES)

    def refresh(self, include_access_codes: bool = False) -> None:
        """Refreshes the Lock state.

        :param include_access_codes: Whether to also refresh access codes.
            If False and access codes were previously fetched, they will be
            preserved from the last refresh.
        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        if not self._auth:
            raise NotAuthenticatedError
        prev_access_codes = self.access_codes
        self._update_with(send(self._auth, request.get_lock(self.device_id)).json())
        if include_access_codes:
            self.refresh_access_codes()
        elif prev_access_codes is not None:
            self.access_codes = prev_access_codes

    def _put_attributes(self, attributes):
        if not self._auth:
            raise NotAuthenticatedError
        resp = send(self._auth, request.put_lock_attributes(self.device_id, attributes))
        self._update_with(resp.json())

    def _toggle(self, lock_state: int):
        if not self._auth:
            raise NotAuthenticatedError
        if self._is_wifi_lock():
            self._put_attributes({"lockState": lock_state})
        else:
            send(
                self._auth,
                request.change_lock_state(
                    self.device_id,
                    cat=self._cat,
                    user_id=self._auth.user_id,
                    lock_state=lock_state,
                ),
            )
            self.is_locked = lock_state == 1
            self.is_jammed = False

    def lock(self):
        """Locks the device.

        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        self._toggle(1)

    def unlock(self):
        """Unlocks the device.

        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        self._toggle(0)

    def last_changed_by(
        self,
        logs: list[LockLog] | None = None,
    ) -> str | None:
        """Determines the last entity or user that changed the lock state.

        :param logs: Unused. Kept for legacy reasons.
        :rtype: str
        """
        _ = logs  # For pylint
        return determine_last_changed_by(self.lock_state_metadata, self.users)

    def keypad_disabled(self, logs: list[LockLog] | None = None) -> bool:
        """Returns True if the keypad is currently disabled.

        :param logs: Recent logs. If None, new logs will be fetched.
        :type logs: list[LockLog] or None
        :rtype: bool
        """
        if logs is None:
            logs = self.logs()
        return is_keypad_disabled(logs)

    def logs(self, limit: int | None = None, sort_desc: bool = False) -> list[LockLog]:
        """Fetches activity logs for the lock.

        :param limit: The number of log entries to return.
        :type limit: int | None
        :param sort_desc: Whether to sort entries in descending order.
        :type sort_desc: bool (defaults to `False`)
        :rtype: list[pyschlage.log.LockLog]
        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        if not self._auth:
            raise NotAuthenticatedError
        resp = send(
            self._auth,
            request.get_logs(self.device_id, limit=limit, sort_desc=sort_desc),
        )
        return [LockLog.from_json(lock_log) for lock_log in resp.json()]

    def refresh_access_codes(self) -> None:
        """Fetches access codes for this lock.

        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        self.access_codes = {}
        for code in self.get_access_codes():
            assert code.access_code_id is not None
            self.access_codes[code.access_code_id] = code

    def get_access_codes(self) -> list[AccessCode]:
        """Fetches the access codes for this lock.

        :rtype list[pyschlage.code.AccessCode]:
        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        """
        if not self._auth:
            raise NotAuthenticatedError

        # Access Codes can be configured to notify the user on use via the app.
        # To make this work, a Notification must also be added, with its ID set
        # to "{user_id}_{access_code_id}". If notifications are disabled for
        # the access code, the Notification's |active| attribute is set to
        # False. In some cases, there may also just not be a Notification
        # added if notifications are disabled.
        notifications: dict[str, Notification] = {}
        user_id_prefix_re = re.compile(rf"^{self._auth.user_id}_")
        for notification in self._get_notifications():
            if notification.notification_type == ON_UNLOCK_ACTION and (
                user_id_prefix_re.match(notification.notification_id)
            ):
                access_code_id = user_id_prefix_re.sub("", notification.notification_id)
                notifications[access_code_id] = notification
        resp = send(self._auth, request.get_access_codes(self.device_id))
        access_codes = []
        for code_json in resp.json():
            access_code = AccessCode.from_json(
                self._auth,
                code_json,
                device=self,
                notification=notifications.get(code_json["accesscodeId"]),
            )
            access_codes.append(access_code)
        return access_codes

    def _get_notifications(self) -> Iterable[Notification]:
        if not self._auth:
            raise NotAuthenticatedError  # pragma: no cover
        resp = send(self._auth, request.get_notifications(self.device_id))
        for notification_json in resp.json():
            notification = Notification.from_json(self._auth, notification_json)
            notification.device_type = self.device_type
            yield notification

    def add_access_code(self, code: AccessCode):
        """Adds an access code to the lock.

        :param code: The access code to add.
        :type code: pyschlage.code.AccessCode
        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        code._auth = self._auth
        code._device = self
        code.save()

    def set_beeper(self, enabled: bool):
        """Sets the beeper_enabled setting.

        :param enabled: Whether the keypress beep should be enabled.
        :type enabled: bool
        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        self._put_attributes({"beeperEnabled": 1 if enabled else 0})

    def set_lock_and_leave(self, enabled: bool):
        """Sets the lock_and_leave setting.

        :param enabled: Whether lock-and-leave should be enabled.
        :type enabled: bool
        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        self._put_attributes({"lockAndLeaveEnabled": 1 if enabled else 0})

    def set_auto_lock_time(self, auto_lock_time: int):
        """Sets the auto_lock_time setting. Setting it to `0` turns off the
        auto-lock feature.

        :param auto_lock_time: Number of seconds of inactivity before the lock
            automatically locks itself. Must be one of :data:`AUTO_LOCK_TIMES`.
        :type auto_lock_time: int
        :raise ValueError: When auto_lock_time is not one of :data:`AUTO_LOCK_TIMES`.
        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        if auto_lock_time not in AUTO_LOCK_TIMES:
            raise ValueError(f"auto_lock_time must be one of: {AUTO_LOCK_TIMES}")
        self._put_attributes({"autoLockTime": auto_lock_time})
