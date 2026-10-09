"""Schlage devices."""

from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Any

from requests import Response

from .common import Mutable
from .exceptions import NotAuthenticatedError


class _MissingAsUnknown(IntEnum):
    """Base class for enums which map unrecognized values to UNKNOWN."""

    @classmethod
    def _missing_(cls, value: object) -> "_MissingAsUnknown":
        return cls["UNKNOWN"]


class AlarmMode(_MissingAsUnknown):
    """The event an armed lock alarm triggers on."""

    UNKNOWN = -1
    DISABLED = 0
    LOCK_UNLOCK = 1
    TAMPER = 2
    FORCED_ENTRY = 3


class BatteryState(_MissingAsUnknown):
    """Coarse battery level reported by the lock."""

    UNKNOWN = -1
    NORMAL = 0
    LOW = 1
    CRITICALLY_LOW = 2


class DoorState(_MissingAsUnknown):
    """State of the door, for locks with a door position sensor."""

    UNKNOWN = 0
    OPEN = 1
    CLOSED = 2
    FAULTY = 3


class OperatingMode(_MissingAsUnknown):
    """Which protocol stack the lock is operating under."""

    UNKNOWN = 0
    SCHLAGE = 1
    HOMEKIT = 2
    SIMULTANEOUS = 3


class DeviceType(str, Enum):
    """Known device types.

    Values are the ``devicetypeId`` prefix reported by the API. The full
    ``devicetypeId`` also carries a transport suffix (``ble``, ``wifi`` or
    ``wb``) and, on later hardware revisions, a generation number, e.g.
    ``be489wifi2``.
    """

    BRIDGE = "br400"
    ARRIVE = "be459"
    SENSE = "be479"
    ENCODE = "be489"
    ENCODE_PLUS = "be499"
    ENCODE_LEVER = "fe789"
    SENSE_PRO = "be889"
    GAINSBOROUGH_SELENE_ENTRANCE = "gselent"
    GAINSBOROUGH_SELENE_SECURE = "gselsec"
    SCHLAGE_SELENE_ENTRANCE = "sselent"
    SCHLAGE_SELENE_SECURE = "sselsec"


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
