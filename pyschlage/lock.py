"""Lock object used for Schlage WiFi devices."""

from __future__ import annotations

from dataclasses import dataclass

from .code import AccessCode
from .common import Mutable
from .exceptions import NotAuthenticatedError
from .log import LockLog


@dataclass
class Lock(Mutable):
    """A Schlage WiFi lock."""

    device_id: str = ""
    """Schlage-generated unique device identifier."""

    name: str = ""
    """User-specified name of the lock."""

    model_name: str = ""
    """The model name of the lock."""

    device_type: str = ""
    """The device type of the lock.

    Also see known device types in device.py.
    """

    battery_level: int | None = None
    """The remaining battery level of the lock.

    This is an integer between 0 and 100 or None if lock is unavailable.
    """

    is_locked: bool | None = False
    """Whether the device is currently locked or None if lock is unavailable."""

    is_jammed: bool | None = False
    """Whether the lock has identified itself as jammed or None if lock is unavailable."""

    firmware_version: str | None = None
    """The firmware version installed on the lock or None if lock is unavailable."""

    _cat: str = ""

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
    def from_json(cls, auth, json):
        """Creates a Lock from a JSON object.

        :meta private:
        """
        is_locked = is_jammed = None
        if "lockState" in json["attributes"]:
            is_locked = json["attributes"]["lockState"] == 1
            is_jammed = json["attributes"]["lockState"] == 2

        return cls(
            _auth=auth,
            device_id=json["deviceId"],
            name=json["name"],
            model_name=json["modelName"],
            device_type=json["devicetypeId"],
            battery_level=json["attributes"].get("batteryLevel"),
            is_locked=is_locked,
            is_jammed=is_jammed,
            firmware_version=json["attributes"].get("mainFirmwareVersion"),
            _cat=json["CAT"],
        )

    def _is_wifi_lock(self) -> bool:
        return self.device_type.startswith("be489") or self.device_type.startswith(
            "be499"
        )

    def refresh(self):
        """Refreshes the Lock state.

        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        path = self.request_path(self.device_id)
        self._update_with(self._auth.request("get", path).json())

    def _send_command(self, command: str, data=dict):
        path = f"{self.request_path(self.device_id)}/commands"
        json = {"data": data, "name": command}
        self._auth.request("post", path, json=json)

    def _toggle(self, lock_state: int):
        if self._is_wifi_lock():
            path = self.request_path(self.device_id)
            json = {"attributes": {"lockState": lock_state}}
            resp = self._auth.request("put", path, json=json)
            self._update_with(resp.json())
        else:
            data = {
                "CAT": self._cat,
                "deviceId": self.device_id,
                "state": lock_state,
                "userId": self._auth.user_id,
            }
            self._send_command("changelockstate", data)
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
        path = LockLog.request_path(self.device_id)
        params = {}
        if limit:
            params["limit"] = limit
        if sort_desc:
            params["sort"] = "desc"
        resp = self._auth.request("get", path, params=params)
        return [LockLog.from_json(l) for l in resp.json()]

    def access_codes(self) -> list[AccessCode]:
        """Fetches access codes for this lock.

        :rtype: list[pyschlage.code.AccessCode]
        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        path = AccessCode.request_path(self.device_id)
        resp = self._auth.request("get", path)
        return [
            AccessCode.from_json(self._auth, ac, self.device_id) for ac in resp.json()
        ]

    def add_access_code(self, code: AccessCode):
        """Adds an access code to the lock.

        :param code: The access code to add.
        :type code: pyschlage.code.AccessCode
        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        if not self._auth:
            raise NotAuthenticatedError
        path = AccessCode.request_path(self.device_id)
        resp = self._auth.request("post", path, json=code.to_json())
        code._auth = self._auth
        code._update_with(resp.json(), self.device_id)
