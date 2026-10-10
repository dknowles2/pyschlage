"""Tests for the Bluetooth LE transport and backend."""

from dataclasses import replace
from typing import Any, Self
from unittest import mock

import cbor2
import pytest

from pyschlage.aio.backend import Setting
from pyschlage.aio.lock import Lock
from pyschlage.ble import backend, framing, uweave
from pyschlage.device import (
    AlarmMode,
    BatteryState,
    DoorState,
    LockState,
    OperatingMode,
)
from pyschlage.exceptions import BleSessionError

from .test_session import CAT, USER_ID, FakeLock, sat


class FakeBleakClient:
    """A bleak client that records writes and replays packets."""

    def __init__(self, device: Any = "AA:BB:CC:00:11:22") -> None:
        self.device = device
        self.writes: list[tuple[str, bytes, bool | None]] = []
        self.notified: list[str] = []
        self.unnotified: list[str] = []
        self.entered = False
        self._callback: Any = None

    async def __aenter__(self) -> Self:
        self.entered = True
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.entered = False

    async def start_notify(self, char: str, callback: Any) -> None:
        self.notified.append(char)
        self._callback = callback

    async def stop_notify(self, char: str) -> None:
        self.unnotified.append(char)

    async def write_gatt_char(
        self, char: str, data: Any, response: bool | None = None
    ) -> None:
        self.writes.append((char, bytes(data), response))
        await self.on_write(bytes(data))

    async def on_write(self, packet: bytes) -> None:
        """Hook for a subclass that answers. The base client stays silent."""

    def send(self, packet: bytes) -> None:
        """Delivers a packet as the lock would."""
        self._callback(None, bytearray(packet))


class FakeRadio(FakeBleakClient):
    """A bleak client that frames for, and answers as, a scripted lock."""

    def __init__(self, device: Any = "AA:BB:CC:00:11:22") -> None:
        super().__init__(device)
        self.lock = FakeLock()
        self._reassembler = framing.Reassembler()
        self._packetizer = framing.Packetizer()

    async def on_write(self, packet: bytes) -> None:
        # The app's own connection request carries a role nibble of zero, which
        # on the receive side means "middle of a record", so the lock has to
        # pick it out by the high bit instead.
        if packet[0] >> 4 >= 8:
            await self.lock.write_connection_request(packet[1:])
        else:
            record = self._reassembler.feed(packet)
            if record is None:
                return
            await self.lock.write(record)
        for reply_packet in self._packetizer.split(await self.lock.read()):
            self.send(reply_packet)


@pytest.fixture
def client() -> FakeBleakClient:
    return FakeBleakClient()


@pytest.fixture
def channel(client: FakeBleakClient) -> backend.GattChannel:
    return backend.GattChannel(client, timeout=0.05)  # type: ignore[arg-type]


@pytest.fixture
def wifi_lock_snapshot(wifi_lock_json: dict[str, Any]) -> Lock:
    return Lock.from_json(wifi_lock_json)


class TestGattChannel:
    async def test_subscribes_and_unsubscribes(
        self, channel: backend.GattChannel, client: FakeBleakClient
    ) -> None:
        await channel.start()
        assert client.notified == [backend.RX_DATA]
        await channel.stop()
        assert client.unnotified == [backend.RX_DATA]

    async def test_write_splits_into_acknowledged_packets(
        self, channel: backend.GattChannel, client: FakeBleakClient
    ) -> None:
        await channel.write(bytes(40))
        assert len(client.writes) == 3
        for char, data, response in client.writes:
            assert char == backend.TX_DATA
            assert len(data) <= framing.PACKET_SIZE
            assert response is True

    async def test_connection_request_is_one_write(
        self, channel: backend.GattChannel, client: FakeBleakClient
    ) -> None:
        await channel.write_connection_request(bytes(40))
        assert len(client.writes) == 1
        assert client.writes[0][1][1:] == bytes(40)

    async def test_read_reassembles(
        self, channel: backend.GattChannel, client: FakeBleakClient
    ) -> None:
        await channel.start()
        for packet in framing.Packetizer().split(b"a" * 30):
            client.send(packet)
        assert await channel.read() == b"a" * 30

    async def test_read_times_out(self, channel: backend.GattChannel) -> None:
        await channel.start()
        with pytest.raises(BleSessionError, match="no record from the lock"):
            await channel.read()

    async def test_read_surfaces_a_bad_packet(
        self, channel: backend.GattChannel, client: FakeBleakClient
    ) -> None:
        await channel.start()
        client.send(bytes([0x02]) + b"junk")
        with pytest.raises(BleSessionError, match="unknown packet role"):
            await channel.read()

    async def test_records_queue_up(
        self, channel: backend.GattChannel, client: FakeBleakClient
    ) -> None:
        await channel.start()
        client.send(bytes([0x0C]) + b"one")
        client.send(bytes([0x1C]) + b"two")
        assert await channel.read() == b"one"
        assert await channel.read() == b"two"


class TestMergeLockState:
    def test_maps_the_lock_state(self, wifi_lock_snapshot: Lock) -> None:
        lock = backend.merge_lock_state(
            wifi_lock_snapshot, {uweave.REPORT_LOCK_STATE: LockState.JAMMED}
        )
        assert lock.is_locked is False
        assert lock.is_jammed is True

    def test_deadlocked_is_locked(self, wifi_lock_snapshot: Lock) -> None:
        lock = backend.merge_lock_state(
            wifi_lock_snapshot, {uweave.REPORT_LOCK_STATE: LockState.DEADLOCKED}
        )
        assert lock.is_locked is True
        assert lock.is_jammed is False

    def test_an_unknown_state_is_unavailable(self, wifi_lock_snapshot: Lock) -> None:
        lock = backend.merge_lock_state(
            wifi_lock_snapshot, {uweave.REPORT_LOCK_STATE: 99}
        )
        assert lock.is_locked is None
        assert lock.is_jammed is None

    def test_takes_the_battery_level(self, wifi_lock_snapshot: Lock) -> None:
        lock = backend.merge_lock_state(
            wifi_lock_snapshot, {uweave.REPORT_BATTERY_LEVEL: 42}
        )
        assert lock.battery_level == 42

    def test_keeps_what_only_the_cloud_knows(self, wifi_lock_snapshot: Lock) -> None:
        lock = backend.merge_lock_state(
            wifi_lock_snapshot, {uweave.REPORT_LOCK_STATE: LockState.UNLOCKED}
        )
        assert lock.name == "Door Lock"
        assert lock.users == wifi_lock_snapshot.users

    def test_takes_the_enum_fields(self, wifi_lock_snapshot: Lock) -> None:
        lock = backend.merge_lock_state(
            wifi_lock_snapshot,
            {
                uweave.REPORT_BATTERY_STATE: 1,
                uweave.REPORT_ALARM_SELECTION: 2,
                uweave.REPORT_OPERATING_MODE: 2,
                uweave.REPORT_DOOR_STATE: 1,
            },
        )
        assert lock.battery_low_state is BatteryState.LOW
        assert lock.alarm_mode is AlarmMode.TAMPER
        assert lock.operating_mode is OperatingMode.HOMEKIT
        assert lock.door_state is DoorState.OPEN

    def test_merges_a_report_a_real_lock_sent(self, wifi_lock_snapshot: Lock) -> None:
        # Verbatim from a BE489WB. Keys 13, 15, 16, 18, 19 and 20 are not
        # described anywhere and are dropped rather than guessed at; 25 is
        # absent, that lock having no door sensor.
        report = {
            0: 0,
            12: 0,
            21: 41,
            13: 0,
            14: 0,
            15: 0,
            16: 0,
            17: 1,
            18: 1,
            19: 17,
            20: "15.00.01367012",
        }
        start = replace(
            wifi_lock_snapshot, is_locked=True, battery_level=95, door_state=None
        )
        lock = backend.merge_lock_state(start, report)
        assert lock.is_locked is False
        assert lock.is_jammed is False
        assert lock.battery_level == 41
        assert lock.battery_low_state is BatteryState.NORMAL
        assert lock.alarm_mode is AlarmMode.DISABLED
        assert lock.operating_mode is OperatingMode.SCHLAGE
        assert lock.door_state is None
        # The firmware version in key 20 goes nowhere: a trait read already
        # reports it, and nothing confirms that is what the key means.
        assert lock.firmware_version == start.firmware_version

    def test_drops_keys_with_no_field(self, wifi_lock_snapshot: Lock) -> None:
        lock = backend.merge_lock_state(wifi_lock_snapshot, {13: 0, 19: 17})
        assert lock == wifi_lock_snapshot

    def test_a_non_map_report_changes_nothing(self, wifi_lock_snapshot: Lock) -> None:
        assert backend.merge_lock_state(wifi_lock_snapshot, None) is wifi_lock_snapshot


class TestBleBackend:
    async def opened(self) -> tuple[backend.BleBackend, FakeLock]:
        lock = FakeLock()
        from pyschlage.ble.session import Session

        session = Session(lock)
        await session.open(sat(), CAT)
        return backend.BleBackend(session, USER_ID), lock

    async def test_set_locked_merges_the_report(self, wifi_lock_snapshot: Lock) -> None:
        ble, lock = await self.opened()
        # Start from a snapshot that disagrees with the report, so a merge that
        # silently did nothing could not pass this.
        start = replace(wifi_lock_snapshot, is_locked=False, battery_level=95)
        lock.replies_with(
            {
                uweave.REPORT_LOCK_STATE: LockState.LOCKED,
                uweave.REPORT_BATTERY_LEVEL: 77,
            }
        )
        got = await ble.set_locked(start, True)
        assert got.is_locked is True
        assert got.battery_level == 77
        params = cbor2.loads(lock.plaintexts[1])[16]
        assert params[1] == uweave.LOCK_STATE_WRITE

    @pytest.mark.parametrize(
        ("setting", "value", "attribute", "field", "want"),
        [
            (Setting.BEEPER_ENABLED, 0, 2, "beeper_enabled", False),
            (Setting.LOCK_AND_LEAVE_ENABLED, 1, 12, "lock_and_leave_enabled", True),
            (Setting.AUTO_LOCK_TIME, 15, 4, "auto_lock_time", 15),
        ],
    )
    async def test_set_setting(
        self,
        wifi_lock_snapshot: Lock,
        setting: Setting,
        value: int,
        attribute: int,
        field: str,
        want: Any,
    ) -> None:
        ble, lock = await self.opened()
        got = await ble.set_setting(wifi_lock_snapshot, setting, value)
        params = cbor2.loads(lock.plaintexts[1])[16]
        assert params[0] == uweave.TRAIT_LOCK_CONFIG
        assert params[1] == attribute
        assert params[2][0] == value
        # The lock does not report the setting back, so the snapshot carries
        # what was asked for.
        assert getattr(got, field) == want

    async def test_get_state_refreshes_from_the_lock(
        self, wifi_lock_snapshot: Lock
    ) -> None:
        ble, lock = await self.opened()
        start = replace(wifi_lock_snapshot, is_locked=True, battery_level=95)
        report = {
            uweave.REPORT_LOCK_STATE: LockState.UNLOCKED,
            uweave.REPORT_BATTERY_LEVEL: 61,
        }
        lock.replies_with_envelope({1: 6, 2: 3, 17: {1: {0: {0: {1: report}}}}})
        got = await ble.get_state(start)
        assert got.is_locked is False
        assert got.battery_level == 61
        # Everything only the cloud knows survives the refresh.
        assert got.name == start.name
        assert got.users == start.users
        assert cbor2.loads(lock.plaintexts[1]) == {1: 6, 2: 3}

    def test_every_setting_has_a_ble_attribute(self) -> None:
        assert set(backend._BLE_ATTRIBUTES) == set(Setting)


class TestDiscover:
    async def test_scans_for_the_uweave_service(self) -> None:
        with mock.patch.object(
            backend.BleakScanner, "discover", new=mock.AsyncMock(return_value=[])
        ) as discover:
            assert await backend.discover(timeout=1.0) == []
        discover.assert_awaited_once_with(
            timeout=1.0, service_uuids=[backend.UWEAVE_SERVICE]
        )


class TestConnect:
    async def test_opens_a_session_and_tears_it_down(
        self, wifi_lock_snapshot: Lock
    ) -> None:
        radio = FakeRadio()
        with mock.patch.object(backend, "BleakClient", return_value=radio):
            async with backend.connect(
                "AA:BB:CC:00:11:22",
                sat=sat().hex(),
                cat=CAT.hex(),
                user_id=USER_ID,
                timeout=1.0,
            ) as ble:
                assert radio.entered
                radio.lock.replies_with({uweave.REPORT_LOCK_STATE: LockState.LOCKED})
                got = await ble.set_locked(
                    replace(wifi_lock_snapshot, is_locked=False), True
                )
                assert got.is_locked is True
        assert radio.unnotified == [backend.RX_DATA]
        assert not radio.entered

    async def test_unsubscribes_when_the_handshake_fails(self) -> None:
        radio = FakeRadio()
        radio.lock.bad_handshake = True
        with (
            mock.patch.object(backend, "BleakClient", return_value=radio),
            pytest.raises(BleSessionError, match="did not verify"),
        ):
            async with backend.connect(
                "AA:BB:CC:00:11:22", sat=sat(), cat=CAT, user_id=USER_ID, timeout=1.0
            ):
                pass  # pragma: no cover
        assert radio.unnotified == [backend.RX_DATA]
