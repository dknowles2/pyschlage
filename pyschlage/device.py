"""Schlage devices."""

from dataclasses import dataclass
from enum import Enum
from typing import Any

from requests import Response

from .common import Mutable
from .exceptions import NotAuthenticatedError


class DeviceType(str, Enum):
    """Known device types."""

    BRIDGE = "br400"
    ARRIVE = "be459"
    SENSE = "be479"
    ENCODE = "be489"
    ENCODE_PLUS = "be499"
    ENCODE_LEVER = "fe789"


@dataclass
class Device(Mutable):
    """Base class for Schlage devices."""

    device_id: str = ""
    """Schlage-generated unique device identifier."""

    device_type: str = ""
    """The device type of the lock."""

    @staticmethod
    def request_path(device_id: str | None = None) -> str:
        """Returns the request path for a Lock.

        :meta private:
        """
        path = "devices"
        if device_id:
            path = f"{path}/{device_id}"
        return path

    def send_command(self, command: str, data: dict[Any, Any]) -> Response:
        """Sends a command to the device."""
        if not self._auth:
            raise NotAuthenticatedError
        path = f"{self.request_path(self.device_id)}/commands"
        json = {"data": data, "name": command}
        return self._auth.request("post", path, json=json)
