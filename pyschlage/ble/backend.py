"""Reaching a lock over Bluetooth LE.

:class:`GattChannel` carries uWeave records over the lock's two
characteristics, framing them on the way out and reassembling them on the way
in. :class:`BleBackend` is a :class:`pyschlage.aio.LockBackend` on top of an
open :class:`pyschlage.ble.session.Session`, so a caller that holds one can
operate a lock without the cloud service in the path.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import Any

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice

from ..aio.backend import Setting
from ..aio.lock import Lock
from ..exceptions import BleSessionError
from ..lock import lock_state_booleans
from . import framing, uweave
from .session import CatMinter, Session

UWEAVE_SERVICE = "883f45ec-14cb-46aa-9864-9a4e782b33d0"
"""The uWeave GATT service."""

RX_DATA = "26002998-e001-4812-8c08-5cd2afda0830"
"""Characteristic the lock sends records on, as indications."""

TX_DATA = "ff530c78-cd50-4bb9-bbd4-0712f32b3796"
"""Characteristic the app writes records to."""

_READ_TIMEOUT = 30.0

# Which attribute of the lock config trait each setting is written to, and the
# type the matching field on a snapshot holds.
_BLE_ATTRIBUTES = {
    Setting.BEEPER_ENABLED: (uweave.BEEPER_ENABLED[1], bool),
    Setting.LOCK_AND_LEAVE_ENABLED: (uweave.LOCK_AND_LEAVE_ENABLED[1], bool),
    Setting.AUTO_LOCK_TIME: (uweave.AUTO_LOCK_TIME[1], int),
}


def merge_lock_state(lock: Lock, report: Any) -> Lock:
    """Merges a lock-state report into a snapshot.

    A report carries only what the lock knows about itself, so the rest of the
    snapshot -- its name, its users, everything the cloud service holds -- is
    carried over unchanged. The battery state, alarm selection, operating mode
    and door state a report also carries have no field on a
    :class:`pyschlage.aio.Lock` and are dropped.

    :param lock: The snapshot to merge into.
    :type lock: pyschlage.aio.Lock
    :param report: The lock-state report, as the lock sent it.
    :rtype: pyschlage.aio.Lock
    """
    if not isinstance(report, dict):
        return lock

    changes: dict[str, Any] = {}
    if uweave.REPORT_LOCK_STATE in report:
        is_locked, is_jammed = lock_state_booleans(report[uweave.REPORT_LOCK_STATE])
        changes["is_locked"] = is_locked
        changes["is_jammed"] = is_jammed
    if uweave.REPORT_BATTERY_LEVEL in report:
        changes["battery_level"] = report[uweave.REPORT_BATTERY_LEVEL]
    return replace(lock, **changes) if changes else lock


class GattChannel:
    """A :class:`pyschlage.ble.session.RecordChannel` over a lock's GATT.

    Create one around a connected :class:`bleak.BleakClient`, call
    :meth:`start` to subscribe, and :meth:`stop` when finished.
    """

    def __init__(self, client: BleakClient, *, timeout: float = _READ_TIMEOUT) -> None:
        """Initializes a GattChannel.

        :param client: A connected bleak client for the lock.
        :type client: bleak.BleakClient
        :param timeout: Seconds to wait for a record before giving up.
        :type timeout: float
        """
        self._client = client
        self._timeout = timeout
        self._packetizer = framing.Packetizer()
        self._reassembler = framing.Reassembler()
        self._records: asyncio.Queue[bytes | Exception] = asyncio.Queue()

    async def start(self) -> None:
        """Subscribes to the records the lock sends.

        The characteristic only supports indications, and bleak subscribes with
        whichever of notifications and indications it advertises.
        """
        await self._client.start_notify(RX_DATA, self._on_packet)

    async def stop(self) -> None:
        """Unsubscribes."""
        await self._client.stop_notify(RX_DATA)

    def _on_packet(
        self, _characteristic: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        # Raising here would only be swallowed by bleak, so hand the problem to
        # whoever is waiting on a record instead.
        try:
            record = self._reassembler.feed(bytes(data))
        except ValueError as ex:
            self._records.put_nowait(ex)
            return
        if record is not None:
            self._records.put_nowait(record)

    async def write_connection_request(self, body: bytes) -> None:
        """Writes an app-initiated connection request, unfragmented.

        :param body: The request body.
        :type body: bytes
        """
        await self._write(self._packetizer.connection_request(body))

    async def write(self, record: bytes) -> None:
        """Writes a record, split across as many packets as it needs.

        :param record: The record to write.
        :type record: bytes
        """
        for packet in self._packetizer.split(record):
            await self._write(packet)

    async def _write(self, packet: bytes) -> None:
        # An acknowledged write, as the app uses. Records above 1024 bytes are
        # additionally blocked by the app, which only matters for firmware
        # images and is not done here.
        await self._client.write_gatt_char(TX_DATA, packet, response=True)

    async def read(self) -> bytes:
        """Reads the next record the lock sends.

        :rtype: bytes
        :raise pyschlage.exceptions.BleSessionError: When no record arrives in
            time, or when the lock sends a packet that cannot be reassembled.
        """
        try:
            record = await asyncio.wait_for(self._records.get(), self._timeout)
        except TimeoutError as ex:
            raise BleSessionError(
                f"no record from the lock within {self._timeout}s"
            ) from ex
        if isinstance(record, Exception):
            raise BleSessionError(str(record)) from record
        return record


class BleBackend:
    """A :class:`pyschlage.aio.LockBackend` that reaches a lock over its radio.

    Only what the lock itself can carry out lives here. Everything the cloud
    service holds -- access codes, logs, users, notifications -- stays with
    :class:`pyschlage.aio.Schlage`.
    """

    def __init__(self, session: Session, user_id: str) -> None:
        """Initializes a BleBackend.

        :param session: An open session with the lock.
        :type session: pyschlage.ble.session.Session
        :param user_id: The account making the changes, which the lock records.
        :type user_id: str
        """
        self._session = session
        self._user_id = user_id

    async def set_locked(self, lock: Lock, locked: bool) -> Lock:
        """Locks or unlocks the device.

        :param lock: The lock to operate.
        :type lock: pyschlage.aio.Lock
        :param locked: True to lock, False to unlock.
        :type locked: bool
        :rtype: pyschlage.aio.Lock
        :raise pyschlage.exceptions.BleSessionError: When the session is not open.
        :raise pyschlage.exceptions.UWeaveError: When the lock reports a failure.
        """
        report = await self._session.set_locked(locked, self._user_id)
        return merge_lock_state(lock, report)

    async def set_setting(self, lock: Lock, setting: Setting, value: int) -> Lock:
        """Writes one of the lock's settings.

        The lock does not report the setting back, so the returned snapshot
        carries what was asked for rather than what the lock stored.

        :param lock: The lock to modify.
        :type lock: pyschlage.aio.Lock
        :param setting: Which setting to write.
        :type setting: pyschlage.aio.Setting
        :param value: The value to write.
        :type value: int
        :rtype: pyschlage.aio.Lock
        :raise pyschlage.exceptions.BleSessionError: When the session is not open.
        :raise pyschlage.exceptions.UWeaveError: When the lock reports a failure.
        """
        attribute, field_type = _BLE_ATTRIBUTES[setting]
        await self._session.write_trait(
            uweave.TRAIT_LOCK_CONFIG, attribute, value, self._user_id
        )
        return replace(lock, **{setting.value: field_type(value)})


async def discover(timeout: float = 10.0) -> list[BLEDevice]:
    """Scans for locks advertising the uWeave service.

    Matching a device to a :class:`pyschlage.aio.Lock` is the caller's
    business. ``Lock.mac_address`` is what the app matches on, which works
    where the platform exposes addresses; macOS reports its own identifiers
    instead, so there the user has to choose the device.

    :param timeout: Seconds to scan for.
    :type timeout: float
    :rtype: list[bleak.backends.device.BLEDevice]
    """
    return await BleakScanner.discover(timeout=timeout, service_uuids=[UWEAVE_SERVICE])


@asynccontextmanager
async def connect(
    device: BLEDevice | str,
    *,
    sat: str | bytes,
    cat: str | bytes,
    user_id: str,
    mint_cat: CatMinter | None = None,
    timeout: float = _READ_TIMEOUT,
) -> AsyncIterator[BleBackend]:
    """Connects to a lock, opens a session and yields a backend for it.

    The session is torn down and the radio link dropped on exit.

    :param device: The lock, or its address.
    :type device: bleak.backends.device.BLEDevice or str
    :param sat: The lock's SAT macaroon, as the hex the cloud service reports
        or as the bytes it decodes to.
    :type sat: str or bytes
    :param cat: The lock's Cloud Access Token, in the same form.
    :type cat: str or bytes
    :param user_id: The account making the changes, which the lock records.
    :type user_id: str
    :param mint_cat: Mints a fresh Cloud Access Token, for the case where the
        lock asks for one.
    :type mint_cat: collections.abc.Callable or None
    :param timeout: Seconds to wait for each record.
    :type timeout: float
    :raise pyschlage.exceptions.BleSessionError: When the handshake fails.
    :raise pyschlage.exceptions.UWeaveError: When the lock rejects the session.
    """
    async with BleakClient(device) as client:
        channel = GattChannel(client, timeout=timeout)
        await channel.start()
        try:
            session = Session(channel, mint_cat)
            await session.open(sat, cat)
            yield BleBackend(session, user_id)
        finally:
            await channel.stop()
