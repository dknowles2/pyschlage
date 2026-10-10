"""Log entries for Schlage WiFi devices."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .common import fromisoformat

_DEFAULT_UUID = "ffffffff-ffff-ffff-ffff-ffffffffffff"
_RESET_LOGS = "RESET_LOGS"
UNKNOWN_EVENT_CODE = -1
"""Event code used when a log entry does not report one."""

LOG_EVENT_TYPES = {
    -1: "Unknown",
    0: "Unknown",
    1: "Locked by keypad",
    2: "Unlocked by keypad",
    3: "Locked by thumbturn",
    4: "Unlocked by thumbturn",
    5: "Locked by 1-touch locking",
    6: "Locked by mobile device",
    7: "Unlocked by mobile device",
    8: "Locked by time",
    9: "Unlocked by time",
    10: "Lock jammed",
    11: "Keypad disabled invalid code",
    12: "Forced entry detected",
    13: "Reserved for power up",
    14: "Access code user added",
    15: "Access code user deleted",
    16: "Mobile user added",
    17: "Mobile user deleted",
    18: "Admin privilege added",
    19: "Admin privilege deleted",
    20: "Firmware updated",
    21: "Low battery indicated",
    22: "Batteries replaced",
    23: "Forced entry alarm silenced",
    24: "All logs cleared",
    25: "Locked by remote",
    26: "Unlocked by remote",
    27: "Hall sensor comm error",
    28: "FDR failed",
    29: "Critical battery state",
    30: "All access code deleted",
    31: "Reserved for future",
    32: "Firmware update failed",
    33: "Bluetooth firmware download failed",
    34: "WiFi firmware download failed",
    35: "Keypad disconnected",
    36: "WiFi AP disconnect",
    37: "WiFi host disconnect",
    38: "WiFi AP connect",
    39: "WiFi host connect",
    40: "User DB failure",
    41: "Reset source",
    42: "WiFi power policy updated",
    43: "WiFi enter roaming",
    44: "WiFi exit roaming",
    45: "WiFi host connect error",
    46: "Watchdog checking fail",
    47: "Locked by scheduled locking",
    48: "Unlocked by inside button",
    49: "Locked by inside button",
    51: "Activity alarm triggered",
    52: "Unlocked by Apple key",
    53: "Locked by Apple key",
    54: "Motor jammed on fail",
    55: "Motor jammed off fail",
    56: "Motor jammed retries exceeded",
    57: "Thread disconnected",
    58: "Thread connected",
    59: "Locked by UWB",
    60: "Unlocked by UWB",
    61: "UWB antenna disconnected",
    62: "Lock lost accurate time",
    64: "Deadlocked by keypad",
    65: "Deadlocked by mobile device",
    66: "Deadlocked by key fob",
    67: "Deadlocked by keypad NFC",
    68: "Unlocked by inside push button",
    69: "Locked by inside push button",
    70: "Unlocked by inside lever",
    71: "Door opened",
    72: "Door closed",
    73: "Door position sensor faulty",
    74: "Locked by key fob",
    75: "Unlocked by key fob",
    76: "Unlocked by mechanical key",
    78: "Key fob user added",
    79: "Key fob user updated",
    80: "Key fob user deleted",
    81: "Locked by linked lock",
    82: "Unlocked by linked lock",
    83: "Deadlocked by linked lock",
    84: "Linked lock paired",
    85: "Linked lock unpaired",
    255: "History cleared",
}

KEYPAD_DISABLED_INVALID_CODE = 11
"""Event code reported when the keypad is disabled due to invalid codes."""

LOGS_CLEARED = 24
"""Event code reported when the lock's history was cleared."""


@dataclass
class LockLog:
    """A lock log entry."""

    created_at: datetime
    """The UTC time at which the log entry was created."""

    message: str
    """The human-readable message associated with the log entry."""

    accessor_id: str | None = None
    """Unique identifier for the user that triggered the log entry."""

    access_code_id: str | None = None
    """Unique identifier for the access code that triggered the log entry."""

    event_code: int = UNKNOWN_EVENT_CODE
    """The raw event code reported by the lock.

    See :data:`LOG_EVENT_TYPES` for the known values.
    """

    @classmethod
    def from_json(cls, json: dict[str, Any]) -> LockLog:
        """Creates a LockLog from a JSON object.

        :meta private:
        """

        def none_if_default(attr):
            return None if attr == _DEFAULT_UUID else attr

        created_at = fromisoformat(json["createdAt"])
        message = json.get("message")
        if not isinstance(message, dict):
            # The API reports a cleared history as the bare string
            # "RESET_LOGS" instead of a message object.
            event_code = LOGS_CLEARED if message == _RESET_LOGS else UNKNOWN_EVENT_CODE
            return cls(
                created_at=created_at,
                message=LOG_EVENT_TYPES[event_code],
                event_code=event_code,
            )

        event_code = message["eventCode"]
        return cls(
            created_at=created_at,
            accessor_id=none_if_default(message["accessorUuid"]),
            access_code_id=none_if_default(message["keypadUuid"]),
            message=LOG_EVENT_TYPES.get(event_code, "Unknown"),
            event_code=event_code,
        )
