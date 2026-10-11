"""Immutable snapshots of Schlage WiFi locks."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, cast

from .. import payload
from ..device import (
    WIFI_DEVICE_TYPES,
    AlarmMode,
    BatteryState,
    DoorState,
    OperatingMode,
)
from ..lock import (
    LockStateMetadata,
    SupportedFeatures,
    auto_lock_times_for,
    determine_last_changed_by,
    is_keypad_disabled,
    lock_diagnostics,
    lock_fields,
    preserve_lock_state_metadata,
)
from ..log import LockLog
from ..user import User


@dataclass(frozen=True, slots=True)
class Lock:
    """A Schlage WiFi lock.

    This is an immutable snapshot of the lock's state at the time it was
    fetched. Methods on :class:`pyschlage.aio.Schlage` that change the lock
    return a new ``Lock`` rather than modifying this one, and two snapshots
    compare equal when the state they describe is the same.
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

    battery_voltage: int | None = None
    """The no-load battery voltage of the lock, in millivolts.

    This is the reading taken with the motor idle, from the lock's reported
    diagnostics. It is None if the lock does not report it.
    """

    is_locked: bool | None = None
    """Whether the device is currently locked or None if lock is unavailable.

    Locks that support deadlocking report True while deadlocked. Locks in
    passage mode report False.
    """

    is_jammed: bool | None = None
    """Whether the lock has identified itself as jammed.

    This is True for both a jammed bolt and a jammed motor. Returns None if
    lock is unavailable.
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

    device_uid: str | None = None
    """The address of the lock's Bluetooth radio, as bare hex.

    Reported only by locks whose Bluetooth address differs from
    :attr:`mac_address`, which is the Encode Plus family; an Encode reports no
    ``deviceUid`` at all. Where both are present, this is the one a Bluetooth
    scan sees, and it comes without the separators :attr:`mac_address` has.
    """

    ble_firmware_version: str | None = None
    """The firmware version of the lock's Bluetooth radio."""

    wifi_firmware_version: str | None = None
    """The firmware version of the lock's WiFi radio.

    This is None for locks without a WiFi radio.
    """

    keypad_firmware_version: str | None = None
    """The firmware version of the lock's keypad."""

    serial_number: str | None = None
    """The serial number of the lock."""

    manufacturer_name: str | None = None
    """The manufacturer name reported by the lock."""

    access_code_length: int | None = None
    """The number of digits in this lock's access codes, or None if unreported.

    Non-positive sentinel values reported by the cloud API (``0`` and ``-1``)
    are mapped to ``None``. The cloud attribute may be unreported (``None``)
    even when the lock has a configured code length: a BE489WB and a BE499WB2
    both report ``0`` to the cloud while answering 4 to the same question asked
    over Bluetooth, which is the read the Schlage app itself trusts. See
    :attr:`supported_features` (``variable_length_access_codes``) to check
    whether the lock accepts variable-length (4 to 8 digit) codes.
    """

    max_user_codes: int | None = None
    """The maximum number of access codes this lock can store."""

    battery_low_state: BatteryState | None = None
    """The coarse battery state reported by the lock.

    This is independent of :attr:`battery_level`; locks may report a low
    battery before the level drops appreciably.
    """

    door_state: DoorState | None = None
    """The state of the door, for locks with a door position sensor.

    This is None for locks without one.
    """

    alarm_mode: AlarmMode | None = None
    """The event the lock's built-in alarm triggers on."""

    alarm_sensitivity: int | None = None
    """The sensitivity of the lock's built-in alarm."""

    operating_mode: OperatingMode | None = None
    """Which protocol stack the lock is operating under."""

    supported_features: SupportedFeatures = field(default_factory=SupportedFeatures)
    """Capabilities advertised by the lock."""

    users: dict[str, User] = field(default_factory=dict)
    """Users with access to this lock, keyed by their ID."""

    _cat: str = field(default="", repr=False, compare=False)

    _sat: str = field(default="", repr=False, compare=False)

    _json: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_json(cls, json: dict[str, Any]) -> Lock:
        """Creates a Lock from a JSON object.

        :meta private:
        """
        return cls(_json=json, **lock_fields(cast(payload.LockJson, json)))

    @property
    def is_wifi_lock(self) -> bool:
        """Whether this lock talks to the cloud service directly over WiFi.

        Locks that do not are reached indirectly, via a bridge, which requires
        a different write path.
        """
        return any(self.device_type.startswith(p) for p in WIFI_DEVICE_TYPES)

    def refreshed(self, json: dict[str, Any]) -> Lock:
        """Returns the snapshot that replaces this one after a fetch or write.

        Who last changed the lock survives a service poll here, as it does
        when a synchronous :class:`pyschlage.lock.Lock` refreshes itself.

        :param json: The lock's JSON, as the service returned it.
        :type json: dict
        :rtype: pyschlage.aio.Lock
        :meta private:
        """
        fresh = Lock.from_json(json)
        return replace(
            fresh,
            lock_state_metadata=preserve_lock_state_metadata(
                self.lock_state_metadata, fresh.lock_state_metadata
            ),
        )

    def auto_lock_times(self) -> tuple[int, ...]:
        """Returns the auto-lock delays this lock supports, in seconds.

        These are the delays :meth:`pyschlage.aio.Schlage.set_auto_lock_time`
        accepts for this lock. A delay of ``0`` turns off the auto-lock feature.

        :rtype: tuple[int, ...]
        """
        return auto_lock_times_for(self.device_type)

    def get_diagnostics(self) -> dict[Any, Any]:
        """Returns a redacted dict of the raw JSON for diagnostics purposes."""
        return lock_diagnostics(self._json)

    def last_changed_by(self) -> str | None:
        """Determines the last entity or user that changed the lock state.

        :rtype: str or None
        """
        return determine_last_changed_by(self.lock_state_metadata, self.users)

    @staticmethod
    def keypad_disabled(logs: list[LockLog]) -> bool:
        """Returns True if the keypad is currently disabled.

        :param logs: Recent logs, as returned by
            :meth:`pyschlage.aio.Schlage.get_logs`.
        :type logs: list[pyschlage.log.LockLog]
        :rtype: bool
        """
        return is_keypad_disabled(logs)
