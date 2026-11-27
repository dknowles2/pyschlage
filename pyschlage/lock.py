"""Lock object used for Schlage WiFi devices."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
import re
from typing import Any

from .auth import Auth
from .code import AccessCode
from .common import redact
from .device import (
    AlarmMode,
    BatteryState,
    Device,
    DeviceType,
    DoorState,
    OperatingMode,
)
from .exceptions import NotAuthenticatedError, UnknownError
from .log import KEYPAD_DISABLED_INVALID_CODE, LockLog
from .notification import ON_UNLOCK_ACTION, Notification
from .user import User

_ENCODE_AUTO_LOCK_TIMES = (0, 15, 30, 60, 120, 240, 360, 600)
_AUTO_LOCK_TIMES_BY_DEVICE_TYPE: dict[DeviceType, tuple[int, ...]] = {
    DeviceType.ENCODE: _ENCODE_AUTO_LOCK_TIMES,
    DeviceType.ARRIVE: _ENCODE_AUTO_LOCK_TIMES,
    DeviceType.GAINSBOROUGH_SELENE_ENTRANCE: _ENCODE_AUTO_LOCK_TIMES,
    DeviceType.GAINSBOROUGH_SELENE_SECURE: _ENCODE_AUTO_LOCK_TIMES,
    DeviceType.SCHLAGE_SELENE_ENTRANCE: _ENCODE_AUTO_LOCK_TIMES,
    DeviceType.SCHLAGE_SELENE_SECURE: _ENCODE_AUTO_LOCK_TIMES,
    DeviceType.ENCODE_PLUS: (0, 15, 30, 60, 120, 240, 300),
    DeviceType.ENCODE_LEVER: (0, 5, 15, 30, 60, 120, 240, 360, 600),
    DeviceType.SENSE: (0, 15, 30, 60, 120, 240),
    DeviceType.SENSE_PRO: (0, 30, 60, 120, 300, 600, 900, 1800),
}

AUTO_LOCK_TIMES = tuple(
    sorted(
        {
            delay
            for delays in _AUTO_LOCK_TIMES_BY_DEVICE_TYPE.values()
            for delay in delays
        }
    )
)

_DEFAULT_ACCESS_CODE_LIMIT = 30
_ACCESS_CODE_LIMIT_BY_DEVICE_TYPE: dict[DeviceType, int] = {
    DeviceType.ENCODE: 100,
    DeviceType.ENCODE_PLUS: 100,
    DeviceType.ENCODE_LEVER: 100,
    DeviceType.ARRIVE: 250,
    DeviceType.SENSE_PRO: 250,
    DeviceType.GAINSBOROUGH_SELENE_ENTRANCE: 250,
    DeviceType.GAINSBOROUGH_SELENE_SECURE: 250,
    DeviceType.SCHLAGE_SELENE_ENTRANCE: 250,
    DeviceType.SCHLAGE_SELENE_SECURE: 250,
}

# Values reported in the lockState attribute. Not all locks report all of
# these: MOTOR_JAMMED, PASSAGE_MODE and DEADLOCKED are only reported by
# newer models.
_LOCK_STATE_UNLOCKED = 0
_LOCK_STATE_LOCKED = 1
_LOCK_STATE_JAMMED = 2
_LOCK_STATE_MOTOR_JAMMED = 4
_LOCK_STATE_PASSAGE_MODE = 5
_LOCK_STATE_DEADLOCKED = 6

_WIFI_DEVICE_TYPE_PREFIXES = (
    DeviceType.ARRIVE,
    DeviceType.ENCODE,
    DeviceType.ENCODE_PLUS,
    DeviceType.ENCODE_LEVER,
    DeviceType.SENSE_PRO,
    DeviceType.GAINSBOROUGH_SELENE_ENTRANCE,
    DeviceType.GAINSBOROUGH_SELENE_SECURE,
    DeviceType.SCHLAGE_SELENE_ENTRANCE,
    DeviceType.SCHLAGE_SELENE_SECURE,
)

_LOCKED_STATES = (_LOCK_STATE_LOCKED, _LOCK_STATE_DEADLOCKED)
_UNLOCKED_STATES = (_LOCK_STATE_UNLOCKED, _LOCK_STATE_PASSAGE_MODE)
_JAMMED_STATES = (_LOCK_STATE_JAMMED, _LOCK_STATE_MOTOR_JAMMED)


def _parse_lock_state(lock_state: int | None) -> tuple[bool | None, bool | None]:
    if lock_state in _LOCKED_STATES + _UNLOCKED_STATES + _JAMMED_STATES:
        return lock_state in _LOCKED_STATES, lock_state in _JAMMED_STATES
    return None, None


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
    def from_json(cls, json: dict) -> LockStateMetadata:
        """Creates a LockStateMetadata from a JSON object.

        :meta private:
        """
        return cls(action_type=json["actionType"], uuid=json["UUID"], name=json["name"])


@dataclass(frozen=True)
class SupportedFeatures:
    """Capabilities advertised by the lock."""

    activity_alarm: bool = False
    """Whether the lock supports the activity alarm."""

    scheduled_locking: bool = False
    """Whether the lock supports locking on a schedule."""

    variable_length_access_codes: bool = False
    """Whether the lock supports variable-length access codes (4 to 8 digits)."""

    wifi_update_command: bool = False
    """Whether the lock accepts the WiFi firmware update command."""

    @classmethod
    def from_json(cls, json: dict[str, Any]) -> SupportedFeatures:
        """Creates a SupportedFeatures from a JSON object.

        :meta private:
        """
        return cls(
            activity_alarm=(json.get("activityAlarm") or 0) >= 1,
            scheduled_locking=(json.get("scheduledLocking") or 0) >= 1,
            variable_length_access_codes=(json.get("vlac") or 0) >= 1,
            wifi_update_command=(json.get("wifiUpdateCommand") or 0) >= 1,
        )


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

    battery_voltage: int | None = None
    """The no-load battery voltage of the lock, in millivolts.

    This is the reading taken with the motor idle, from the lock's reported
    diagnostics. It is None if the lock does not report it.
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
    """The number of digits in this lock's access codes, or None if unreported.

    Non-positive sentinel values reported by the cloud API (``0`` and ``-1``)
    are mapped to ``None``. The cloud attribute may be unreported (``None``)
    even when the lock has a configured code length; see
    :attr:`supported_features` (``variable_length_access_codes``) to check
    whether the lock accepts variable-length (4 to 8 digit) codes.
    """

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

    supported_features: SupportedFeatures = field(default_factory=SupportedFeatures)
    """Capabilities advertised by the lock."""

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
        attributes = json["attributes"]
        is_locked, is_jammed = _parse_lock_state(attributes.get("lockState"))

        lock_state_metadata = None
        if "lockStateMetadata" in attributes:
            lock_state_metadata = LockStateMetadata.from_json(
                attributes["lockStateMetadata"]
            )

        users: dict[str, User] = {}
        for user_json in json.get("users", []):
            user = User.from_json(user_json)
            users[user.user_id] = user

        def enum_or_none(enum, attr):
            value = attributes.get(attr)
            return None if value is None else enum(value)

        supported_features = SupportedFeatures.from_json(
            attributes.get("supportedFeatures") or {}
        )
        raw_access_code_length = attributes.get("accessCodeLength")
        access_code_length = (
            raw_access_code_length
            if type(raw_access_code_length) is int and raw_access_code_length > 0
            else None
        )

        return cls(
            _auth=auth,
            device_id=json["deviceId"],
            name=json["name"],
            model_name=json.get("modelName", ""),
            device_type=json["devicetypeId"],
            connected=json.get("connected", False),
            battery_level=attributes.get("batteryLevel"),
            battery_voltage=(attributes.get("diagnostics") or {}).get("noLoadVoltage"),
            is_locked=is_locked,
            is_jammed=is_jammed,
            lock_state_metadata=lock_state_metadata,
            beeper_enabled=attributes.get("beeperEnabled") == 1,
            lock_and_leave_enabled=attributes.get("lockAndLeaveEnabled") == 1,
            auto_lock_time=attributes.get("autoLockTime", 0),
            firmware_version=attributes.get("mainFirmwareVersion"),
            ble_firmware_version=attributes.get("bleFirmwareVersion"),
            wifi_firmware_version=attributes.get("wifiFirmwareVersion"),
            keypad_firmware_version=attributes.get("keypadFirmwareVersion"),
            mac_address=attributes.get("macAddress"),
            serial_number=attributes.get("serialNumber"),
            manufacturer_name=attributes.get("manufacturerName"),
            access_code_length=access_code_length,
            max_user_codes=attributes.get("maxUserCodes"),
            battery_low_state=enum_or_none(BatteryState, "batteryLowState"),
            door_state=enum_or_none(DoorState, "doorState"),
            alarm_mode=enum_or_none(AlarmMode, "alarmSelection"),
            alarm_sensitivity=attributes.get("alarmSensitivity"),
            operating_mode=enum_or_none(OperatingMode, "opMode"),
            supported_features=supported_features,
            users=users,
            _cat=json.get("CAT", ""),
            _json=json,
        )

    def get_diagnostics(self) -> dict[Any, Any]:
        """Returns a redacted dict of the raw JSON for diagnostics purposes."""
        return redact(
            self._json,
            allowed=[
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
                "attributes.diagnostics.currentVoltage",
                "attributes.diagnostics.filterVoltage",
                "attributes.diagnostics.noLoadVoltage",
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
            ],
        )

    def _is_wifi_lock(self) -> bool:
        for prefix in _WIFI_DEVICE_TYPE_PREFIXES:
            if self.device_type.startswith(prefix):
                return True
        return False

    def _update_with(self, json: dict[str, Any], *args: Any, **kwargs: Any) -> None:
        prev_metadata = self.lock_state_metadata
        super()._update_with(json, *args, **kwargs)
        if (
            self.lock_state_metadata is not None
            and self.lock_state_metadata.action_type == "deepQuery"
            and prev_metadata is not None
        ):
            self.lock_state_metadata = prev_metadata

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
        path = self.request_path(self.device_id)
        prev_access_codes = self.access_codes
        self._update_with(self._auth.request("get", path).json())
        if include_access_codes:
            self.refresh_access_codes()
        elif prev_access_codes is not None:
            self.access_codes = prev_access_codes

    def _put_attributes(self, attributes):
        if not self._auth:
            raise NotAuthenticatedError
        path = self.request_path(self.device_id)
        json = {"attributes": attributes}
        resp = self._auth.request("put", path, json=json)
        self._update_with(resp.json())

    def _toggle(self, lock_state: int):
        if not self._auth:
            raise NotAuthenticatedError
        if self._is_wifi_lock():
            self._toggle_wifi(lock_state)
        else:
            self._toggle_bridge(lock_state)

    def _toggle_wifi(self, lock_state: int):
        self._put_attributes({"lockState": lock_state})

    def _toggle_bridge(self, lock_state: int):
        if not self._auth:
            raise NotAuthenticatedError  # pragma: no cover
        data = {
            "CAT": self._cat,
            "deviceId": self.device_id,
            "state": lock_state,
            "userId": self._auth.user_id,
        }
        resp = self.send_command("changelockstate", data)
        resp_json = resp.json()
        result = resp_json.get("result") if isinstance(resp_json, dict) else None
        if not isinstance(result, dict):
            error = resp_json.get("error") if isinstance(resp_json, dict) else None
            message = error.get("message") if isinstance(error, dict) else None
            status_code = error.get("statusCode") if isinstance(error, dict) else None
            raise UnknownError(
                message or "Failed to change lock state",
                status_code=(status_code if type(status_code) is int else None),
            )
        if "state" in result or "lockState" in result:
            raw_state = result["state"] if "state" in result else result["lockState"]
            self.is_locked, self.is_jammed = _parse_lock_state(raw_state)
        if (battery_level := result.get("batteryLevel")) is not None:
            self.battery_level = battery_level
        raw_alarm = (
            result.get("alarmSelection")
            if "alarmSelection" in result
            else result.get("alarmEnabled")
        )
        if raw_alarm is not None:
            self.alarm_mode = AlarmMode(raw_alarm)

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
        :rtype: str | None
        """
        _ = logs  # For pylint
        if self.lock_state_metadata is None:
            return None

        user_suffix = ""
        uuid = self.lock_state_metadata.uuid
        if uuid is not None and (user := self.users.get(uuid)):
            user_suffix = f" - {user.name}"

        match self.lock_state_metadata.action_type:
            case "deepQuery":
                return None
            case "thumbTurn":
                return "thumbturn"
            case "1touchLocking":
                return "1-touch locking"
            case "accesscode":
                return f"keypad - {self.lock_state_metadata.name}"
            case "AppleHomeNFC":
                return f"apple nfc device{user_suffix}"
            case "virtualKey":
                return f"mobile device{user_suffix}"
        return "unknown"

    def keypad_disabled(self, logs: list[LockLog] | None = None) -> bool:
        """Returns True if the keypad is currently disabled.

        :param logs: Recent logs. If None, new logs will be fetched.
        :type logs: list[LockLog] or None
        :rtype: bool
        """
        if logs is None:
            logs = self.logs()
        if not logs:
            return False
        newest_log = max(logs, key=lambda log: log.created_at)
        return newest_log.event_code == KEYPAD_DISABLED_INVALID_CODE

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
        path = LockLog.request_path(self.device_id)
        params: dict[str, Any] = {}
        if limit:
            params["limit"] = limit
        if sort_desc:
            params["sort"] = "desc"
        resp = self._auth.request("get", path, params=params)
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

    def _access_code_limit(self) -> int:
        if self.max_user_codes and self.max_user_codes > 0:
            return self.max_user_codes
        for prefix, limit in _ACCESS_CODE_LIMIT_BY_DEVICE_TYPE.items():
            if self.device_type.startswith(prefix):
                return limit
        return _DEFAULT_ACCESS_CODE_LIMIT

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
        path = AccessCode.request_path(self.device_id)
        params = {"limit": self._access_code_limit()}
        resp = self._auth.request("get", path, params=params)
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
        path = Notification.request_path()
        params = {"deviceId": self.device_id}
        resp = self._auth.request("get", path, params=params)
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

    def auto_lock_times(self) -> tuple[int, ...]:
        """Returns the auto-lock delays this lock supports, in seconds.

        These are the delays :meth:`set_auto_lock_time` accepts. A delay of `0`
        turns off the auto-lock feature.

        :rtype: tuple[int, ...]
        """
        for prefix, times in _AUTO_LOCK_TIMES_BY_DEVICE_TYPE.items():
            if self.device_type.startswith(prefix):
                return times
        return AUTO_LOCK_TIMES

    def set_auto_lock_time(self, auto_lock_time: int):
        """Sets the auto_lock_time setting. Setting it to `0` turns off the
        auto-lock feature.

        :param auto_lock_time: Number of seconds of inactivity before the lock
            automatically locks itself. Must be one of :meth:`auto_lock_times`.
        :type auto_lock_time: int
        :raise ValueError: When auto_lock_time is not supported by this lock.
        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        valid_times = self.auto_lock_times()
        if auto_lock_time not in valid_times:
            raise ValueError(f"auto_lock_time must be one of: {valid_times}")
        self._put_attributes({"autoLockTime": auto_lock_time})
