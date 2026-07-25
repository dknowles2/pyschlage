"""Schlage devices."""

from __future__ import annotations

from enum import Enum


class DeviceType(str, Enum):
    """Known device types."""

    BRIDGE = "br400"
    ARRIVE = "be459"
    SENSE = "be479"
    ENCODE = "be489"
    ENCODE_PLUS = "be499"
    ENCODE_LEVER = "fe789"


#: Device types that talk to the cloud service directly over WiFi. Everything
#: else is reached indirectly, via a bridge.
WIFI_DEVICE_TYPES = (
    DeviceType.ARRIVE,
    DeviceType.ENCODE,
    DeviceType.ENCODE_PLUS,
    DeviceType.ENCODE_LEVER,
)
