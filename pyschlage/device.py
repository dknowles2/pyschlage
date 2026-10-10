"""Schlage devices."""

from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Any

from requests import Response

from . import request
from .common import Mutable, send
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


WIFI_DEVICE_TYPES = (
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
"""``devicetypeId`` prefixes of devices that talk to the cloud service
directly over WiFi. Devices not listed here are reached indirectly, via a
bridge, which requires a different write path."""


@dataclass
class Device(Mutable):
    """Base class for Schlage devices."""

    device_id: str = ""
    """Schlage-generated unique device identifier."""

    device_type: str = ""
    """The device type of the lock."""

    def send_command(self, command: str, data: dict[Any, Any]) -> Response:
        """Sends a command to the device."""
        if not self._auth:
            raise NotAuthenticatedError
        return send(self._auth, request.send_command(self.device_id, command, data))
