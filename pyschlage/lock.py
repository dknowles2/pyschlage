"""Lock object used for Schlage WiFi devices."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .auth import Auth
from .code import AccessCode
from .common import redact
from .device import Device
from .exceptions import NotAuthenticatedError
from .log import LockLog
from .notification import ON_UNLOCK_ACTION, Notification
from .user import User

AUTO_LOCK_TIMES = (0, 5, 15, 30, 60, 120, 240, 300)


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
    """Whether the device is currently locked or None if lock is unavailable."""

    is_jammed: bool | None = False
    """Whether the lock has identified itself as jammed.

    Returns None if lock is unavailable.
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

    mac_address: str | None = None
    """The MAC address for the lock or None if lock is unavailable."""

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
            _auth=auth,
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

    def get_diagnostics(self) -> dict[Any, Any]:
        """Returns a redacted dict of the raw JSON for diagnostics purposes."""
        return redact(
            self._json,
            allowed=[
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
            ],
        )

    def _is_wifi_lock(self) -> bool:
        for prefix in ("be489", "be499", "fe789"):
            if self.device_type.startswith(prefix):
                return True
        return False

    def refresh(self, include_access_codes: bool = False) -> None:
        """Refreshes the Lock state.

        :param include_access_codes: Whether to also refresh access codes.
        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        if not self._auth:
            raise NotAuthenticatedError
        path = self.request_path(self.device_id)
        self._update_with(self._auth.request("get", path).json())
        if include_access_codes:
            self.refresh_access_codes()

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
            self._put_attributes({"lockState": lock_state})
        else:
            data = {
                "CAT": self._cat,
                "deviceId": self.device_id,
                "state": lock_state,
                "userId": self._auth.user_id,
            }
            self.send_command("changelockstate", data)
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
        newest_log = sorted(logs, reverse=True, key=lambda log: log.created_at)[0]
        return newest_log.message == "Keypad disabled invalid code"

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
        user_id_len = len(self._auth.user_id)
        for notification in self._get_notifications():
            if notification.notification_type == ON_UNLOCK_ACTION:
                if not notification.notification_id.startswith(self._auth.user_id):
                    # This shouldn't happen, but ignore it just in case.
                    continue  # pragma: no cover
                access_code_id = notification.notification_id[user_id_len + 1 :]
                notifications[access_code_id] = notification
        path = AccessCode.request_path(self.device_id)
        resp = self._auth.request("get", path)
        access_codes = []
        for code_json in resp.json():
            access_code = AccessCode.from_json(self._auth, code_json, device=self)
            access_code.device_id = self.device_id
            if access_code.access_code_id in notifications:
                access_code._notification = notification
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
        """Sets the beeper_enabled setting."""
        self._put_attributes({"beeperEnabled": 1 if enabled else 0})

    def set_lock_and_leave(self, enabled: bool):
        """Sets the lock_and_leave setting."""
        self._put_attributes({"lockAndLeaveEnabled": 1 if enabled else 0})

    def set_auto_lock_time(self, auto_lock_time: int):
        """Sets the auto_lock_time setting. Setting it to `0` turns off the
        auto-lock feature."""
        if auto_lock_time not in AUTO_LOCK_TIMES:
            raise ValueError(f"auto_lock_time must be one of: {AUTO_LOCK_TIMES}")
        self._put_attributes({"autoLockTime": auto_lock_time})
