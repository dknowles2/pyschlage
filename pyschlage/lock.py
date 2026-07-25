"""Lock object used for Schlage WiFi devices."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .common import redact
from .device import WIFI_DEVICE_TYPES
from .log import KEYPAD_DISABLED_MESSAGE, LockLog
from .user import User

AUTO_LOCK_TIMES = (0, 5, 15, 30, 60, 120, 240, 300, 360, 600)

_DIAGNOSTICS_ALLOWED = [
    "attributes.accessCodeLength",
    "attributes.actAlarmBuzzerEnabled",
    "attributes.actAlarmState",
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
    "attributes.firmwareUpdate",
    "attributes.homePosCurrentMax",
    "attributes.keypadFirmwareVersion",
    "attributes.lockAndLeaveEnabled",
    "attributes.lockState",
    "attributes.lockStateMetadata",
    "attributes.mainFirmwareVersion",
    "attributes.mode",
    "attributes.modelName",
    "attributes.periodicDeepQueryTimeSetting",
    "attributes.psPollEnabled",
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


@dataclass(frozen=True, slots=True)
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
        return cls(action_type=json["actionType"], uuid=json["UUID"], name=json["name"])


@dataclass(frozen=True, slots=True)
class Lock:
    """A Schlage WiFi lock.

    This is an immutable snapshot of the lock's state at the time it was
    fetched. Methods on :class:`pyschlage.Schlage` that change the lock return
    a new ``Lock`` rather than modifying this one.
    """

    device_id: str
    """Schlage-generated unique device identifier."""

    device_type: str = ""
    """The device type of the lock."""

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

    is_locked: bool | None = None
    """Whether the device is currently locked or None if lock is unavailable."""

    is_jammed: bool | None = None
    """Whether the lock has identified itself as jammed.

    Returns None if lock is unavailable.
    """

    lock_state_metadata: LockStateMetadata | None = None
    """Metadata about the current lock state."""

    beeper_enabled: bool = False
    """Whether the keypress beep is enabled."""

    lock_and_leave_enabled: bool = False
    """Whether lock-and-leave (a.k.a. "1-Touch Locking") feature is enabled."""

    auto_lock_time: int = 0
    """Time (in seconds) after which the lock will automatically lock itself."""

    firmware_version: str | None = None
    """The firmware version installed on the lock or None if lock is unavailable."""

    mac_address: str | None = None
    """The MAC address for the lock or None if lock is unavailable."""

    users: dict[str, User] = field(default_factory=dict)
    """Users with access to this lock, keyed by their ID."""

    _cat: str = field(default="", repr=False, compare=False)

    _json: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @staticmethod
    def request_path(device_id: str | None = None) -> str:
        """Returns the request path for a Lock.

        :meta private:
        """
        path = "devices"
        if device_id:
            path = f"{path}/{device_id}"
        return path

    @classmethod
    def from_json(cls, json: dict[str, Any]) -> Lock:
        """Creates a Lock from a JSON object.

        :meta private:
        """
        is_locked = is_jammed = None
        attributes = json["attributes"]
        if "lockState" in attributes:
            is_locked = attributes["lockState"] == 1
            is_jammed = attributes["lockState"] == 2

        lock_state_metadata = None
        if "lockStateMetadata" in attributes:
            lock_state_metadata = LockStateMetadata.from_json(
                attributes["lockStateMetadata"]
            )

        users: dict[str, User] = {}
        for user_json in json.get("users", []):
            user = User.from_json(user_json)
            users[user.user_id] = user

        return cls(
            device_id=json["deviceId"],
            name=json["name"],
            model_name=json.get("modelName", ""),
            device_type=json["devicetypeId"],
            connected=json.get("connected", False),
            battery_level=attributes.get("batteryLevel"),
            is_locked=is_locked,
            is_jammed=is_jammed,
            lock_state_metadata=lock_state_metadata,
            beeper_enabled=attributes.get("beeperEnabled") == 1,
            lock_and_leave_enabled=attributes.get("lockAndLeaveEnabled") == 1,
            auto_lock_time=attributes.get("autoLockTime", 0),
            firmware_version=attributes.get("mainFirmwareVersion"),
            mac_address=attributes.get("macAddress"),
            users=users,
            _cat=json.get("CAT", ""),
            _json=json,
        )

    @property
    def is_wifi_lock(self) -> bool:
        """Whether this lock talks to the cloud service directly over WiFi.

        Locks that do not are reached indirectly, via a bridge, which requires
        a different write path.
        """
        return any(self.device_type.startswith(p) for p in WIFI_DEVICE_TYPES)

    def get_diagnostics(self) -> dict[str, Any]:
        """Returns a redacted dict of the raw JSON for diagnostics purposes."""
        return redact(self._json, allowed=_DIAGNOSTICS_ALLOWED)

    def last_changed_by(self) -> str | None:
        """Determines the last entity or user that changed the lock state.

        :rtype: str | None
        """
        if self.lock_state_metadata is None:
            return None

        user_suffix = ""
        uuid = self.lock_state_metadata.uuid
        if uuid is not None and (user := self.users.get(uuid)):
            user_suffix = f" - {user.name}"

        match self.lock_state_metadata.action_type:
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

    @staticmethod
    def keypad_disabled(logs: list[LockLog]) -> bool:
        """Returns True if the keypad is currently disabled.

        :param logs: Recent logs, as returned by
            :meth:`pyschlage.Schlage.get_logs`.
        :type logs: list[pyschlage.log.LockLog]
        :rtype: bool
        """
        if not logs:
            return False
        newest_log = max(logs, key=lambda log: log.created_at)
        return newest_log.message == KEYPAD_DISABLED_MESSAGE
