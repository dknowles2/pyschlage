"""Lock object used for Schlage WiFi devices."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .code import AccessCode
from .common import Mutable
from .exceptions import NotAuthenticatedError
from .log import LockLog


class DeviceType(str, Enum):
    """Known device types."""

    BRIDGE = "br400"
    DENALI = "be489"
    DENALI_BLE = "be489ble"
    DENALI_MCKINLEY = "be489wb2"
    DENALI_MCKINLEY_BLE = "be489ble2"
    DENALI_MCKINLEY_WIFI = "be489wifi2"
    DENALI_WIFI = "be489wifi"
    ENCODE_LEVER = "fe789"
    ENCODE_LEVER_BLE = "fe789ble"
    ENCODE_LEVER_MCKINLEY = "fe789wb2"
    ENCODE_LEVER_MCKINLEY_BLE = "fe789ble2"
    ENCODE_LEVER_MCKINLEY_WIFI = "fe789wifi2"
    ENCODE_LEVER_WIFI = "fe789wifi"
    JACKALOPE = "be499"
    JACKALOPE_BLE = "be499ble"
    JACKALOPE_MCKINLEY = "be499wb2"
    JACKALOPE_MCKINLEY_BLE = "be499ble2"
    JACKALOPE_MCKINLEY_WIFI = "be499wifi2"
    JACKALOPE_WIFI = "be499wifi"
    SENSE = "be479"


@dataclass
class Lock(Mutable):
    """A Schlage WiFi lock."""

    device_id: str = ""
    name: str = ""
    model_name: str = ""
    device_type: str = ""
    battery_level: int = 0
    is_locked: bool = False
    is_jammed: bool = False
    firmware_version: str = ""
    _cat: str = ""

    @staticmethod
    def request_path(device_id: str | None = None) -> str:
        """Returns the request path for a Lock."""
        path = "devices"
        if device_id:
            path = f"{path}/{device_id}"
        return path

    @classmethod
    def from_json(cls, auth, json):
        """Creates a Lock from a JSON object."""
        return cls(
            _auth=auth,
            device_id=json["deviceId"],
            name=json["name"],
            model_name=json["modelName"],
            device_type=json["devicetypeId"],
            battery_level=json["attributes"]["batteryLevel"],
            is_locked=json["attributes"]["lockState"] == 1,
            is_jammed=json["attributes"]["lockState"] == 2,
            firmware_version=json["attributes"]["mainFirmwareVersion"],
            _cat=json["CAT"],
        )

    def _is_wifi_lock(self) -> bool:
        return self.device_type.startswith("be489") or self.device_type.startswith(
            "be499"
        )

    def refresh(self):
        """Refreshes the Lock state."""
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
        """Locks the device."""
        self._toggle(1)

    def unlock(self):
        """Unlocks the device."""
        self._toggle(0)

    def logs(self, limit: int | None = None, sort_desc: bool = False) -> list[LockLog]:
        """Fetches activity logs for the lock."""
        path = LockLog.request_path(self.device_id)
        params = {}
        if limit:
            params["limit"] = limit
        if sort_desc:
            params["sort"] = "desc"
        resp = self._auth.request("get", path, params=params)
        return [LockLog.from_json(l) for l in resp.json()]

    def access_codes(self) -> list[AccessCode]:
        """Fetches access codes for this lock."""
        path = AccessCode.request_path(self.device_id)
        resp = self._auth.request("get", path)
        return [
            AccessCode.from_json(self._auth, ac, self.device_id) for ac in resp.json()
        ]

    def add_access_code(self, code: AccessCode):
        """Adds an access code to the lock."""
        if not self._auth:
            raise NotAuthenticatedError
        path = AccessCode.request_path(self.device_id)
        resp = self._auth.request("post", path, json=code.to_json())
        code._auth = self._auth
        code._update_with(resp.json(), self.device_id)
