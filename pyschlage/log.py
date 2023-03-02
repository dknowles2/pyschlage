"""Log entries for Schlage WiFi devices."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import time

_DEFAULT_UUID = "ffffffff-ffff-ffff-ffff-ffffffffffff"
LOG_EVENT_TYPES = {
    -1: "Unknown",
    0: "Unknown",
    1: "Locked by keypad",
    2: "Unlocked by keypad",
    3: "Locked by thumbturn",
    4: "Unlocked by thumbturn",
    5: "Locked by Schlage button",
    6: "Locked by mobile device",
    7: "Unlocked by mobile device",
    8: "Locked by time",
    9: "Unlocked by time",
    10: "Lock jammed",
    11: "Keypad disabled invalid code",
    12: "Alarm triggered",
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
    27: "Hall sensor comm error",
    28: "FDR failed",
    29: "Critical battery state",
    30: "All access code deleted",
    32: "Firmware update failed",
    33: "Bluetooth firmware download failed",
    34: "WiFi firmware download failed",
    35: "Keypad disconnected",
    36: "WiFi AP disconnect",
    37: "WiFi host disconnect",
    38: "WiFi AP connect",
    39: "WiFi host connect",
    40: "User DB failure",
    48: "Passage mode activated",
    49: "Passage mode deactivated",
    52: "Unlocked by Apple key",
    53: "Locked by Apple key",
    54: "Motor jammed on fail",
    55: "Motor jammed off fail",
    56: "Motor jammed retries exceeded",
    255: "History cleared",
}


def _utc2local(utc: datetime) -> datetime:
    """Converts a UTC datetime to localtime."""
    epoch = time.mktime(utc.timetuple())
    offset = datetime.fromtimestamp(epoch) - datetime.utcfromtimestamp(epoch)
    return (utc + offset).replace(tzinfo=None)


@dataclass
class LockLog:
    """A lock log entry."""

    created_at: datetime
    """The time at which the log entry was created."""

    accessor_id: str | None
    """Unique identifier for the user that triggered the log entry."""

    access_code_id: str | None
    """Unique identifier for the access code that triggered the log entry."""

    message: str
    """The human-readable message associated with the log entry."""

    @staticmethod
    def request_path(device_id: str) -> str:
        """Returns the request path for the LockLog.

        :meta private:
        """
        return f"devices/{device_id}/logs"

    @classmethod
    def from_json(cls, json):
        """Creates a LockLog from a JSON object.

        :meta private:
        """
        # datetime.fromisoformat() doesn't like fractional seconds with a "Z"
        # suffix. This seems to fix it.
        created_at_str = json["createdAt"].rstrip("Z") + "+00:00"
        none_if_default = lambda x: None if x == _DEFAULT_UUID else x
        return cls(
            created_at=_utc2local(datetime.fromisoformat(created_at_str)),
            accessor_id=none_if_default(json["message"]["accessorUuid"]),
            access_code_id=none_if_default(json["message"]["keypadUuid"]),
            message=LOG_EVENT_TYPES.get(json["message"]["eventCode"], "Unknown"),
        )
