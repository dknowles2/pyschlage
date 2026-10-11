"""Tests for the lock backend seam."""

from typing import Any

import pytest

from pyschlage import request
from pyschlage.aio.backend import _CLOUD_ATTRIBUTES, CloudBackend, Setting
from pyschlage.aio.client import Schlage
from pyschlage.aio.lock import Lock

from .test_client import USER_ID, FakeTransport


class FakeBackend:
    """A LockBackend that records what it was asked to do."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    async def set_locked(self, lock: Lock, locked: bool) -> Lock:
        self.calls.append(("set_locked", lock.device_id, locked))
        return lock

    async def set_setting(self, lock: Lock, setting: Setting, value: int) -> Lock:
        self.calls.append(("set_setting", lock.device_id, setting, value))
        return lock


@pytest.fixture
def transport() -> FakeTransport:
    return FakeTransport()


@pytest.fixture
def backend(transport: FakeTransport) -> CloudBackend:
    return CloudBackend(transport, USER_ID)


@pytest.fixture
def wifi_lock_snapshot(wifi_lock_json: dict[str, Any]) -> Lock:
    return Lock.from_json(wifi_lock_json)


@pytest.fixture
def ble_lock_snapshot(ble_lock_json: dict[str, Any]) -> Lock:
    return Lock.from_json(ble_lock_json)


class TestSettings:
    def test_every_setting_has_a_cloud_attribute(self) -> None:
        # A Setting with no mapping would raise a KeyError at the worst moment.
        assert set(_CLOUD_ATTRIBUTES) == set(Setting)


class TestCloudBackend:
    async def test_set_locked_wifi(
        self,
        backend: CloudBackend,
        transport: FakeTransport,
        wifi_lock_json: dict[str, Any],
        wifi_lock_snapshot: Lock,
    ) -> None:
        transport.returns(wifi_lock_json)
        lock = await backend.set_locked(wifi_lock_snapshot, True)
        assert lock.is_locked
        assert transport.request == request.put_lock_attributes(
            "__wifi_uuid__", {"lockState": 1}
        )

    async def test_set_unlocked_wifi(
        self,
        backend: CloudBackend,
        transport: FakeTransport,
        wifi_lock_json: dict[str, Any],
        wifi_lock_snapshot: Lock,
    ) -> None:
        transport.returns(wifi_lock_json)
        await backend.set_locked(wifi_lock_snapshot, False)
        assert transport.request == request.put_lock_attributes(
            "__wifi_uuid__", {"lockState": 0}
        )

    async def test_set_locked_bridge(
        self,
        backend: CloudBackend,
        transport: FakeTransport,
        ble_lock_snapshot: Lock,
    ) -> None:
        lock = await backend.set_locked(ble_lock_snapshot, True)
        assert lock.is_locked
        assert lock.is_jammed is False
        assert transport.request == request.change_lock_state(
            "__ble_uuid__", cat="abcdef", user_id=USER_ID, lock_state=1
        )

    @pytest.mark.parametrize(
        ("setting", "value", "attribute"),
        [
            (Setting.BEEPER_ENABLED, 0, "beeperEnabled"),
            (Setting.LOCK_AND_LEAVE_ENABLED, 1, "lockAndLeaveEnabled"),
            (Setting.AUTO_LOCK_TIME, 15, "autoLockTime"),
        ],
    )
    async def test_set_setting(
        self,
        backend: CloudBackend,
        transport: FakeTransport,
        wifi_lock_json: dict[str, Any],
        wifi_lock_snapshot: Lock,
        setting: Setting,
        value: int,
        attribute: str,
    ) -> None:
        transport.returns(wifi_lock_json)
        await backend.set_setting(wifi_lock_snapshot, setting, value)
        assert transport.request == request.put_lock_attributes(
            "__wifi_uuid__", {attribute: value}
        )


class TestClientDispatch:
    """The client's lock writes go through whichever backend it was given."""

    @pytest.fixture
    def fake_backend(self) -> FakeBackend:
        return FakeBackend()

    @pytest.fixture
    def schlage(self, transport: FakeTransport, fake_backend: FakeBackend) -> Schlage:
        return Schlage(transport, USER_ID, backend=fake_backend)

    async def test_set_locked(
        self,
        schlage: Schlage,
        fake_backend: FakeBackend,
        transport: FakeTransport,
        wifi_lock_snapshot: Lock,
    ) -> None:
        await schlage.set_locked(wifi_lock_snapshot, True)
        assert fake_backend.calls == [("set_locked", "__wifi_uuid__", True)]
        # The backend owns the request, so the client issued none itself.
        assert transport.requests == []

    async def test_set_beeper(
        self, schlage: Schlage, fake_backend: FakeBackend, wifi_lock_snapshot: Lock
    ) -> None:
        await schlage.set_beeper(wifi_lock_snapshot, True)
        assert fake_backend.calls == [
            ("set_setting", "__wifi_uuid__", Setting.BEEPER_ENABLED, 1)
        ]

    async def test_set_lock_and_leave(
        self, schlage: Schlage, fake_backend: FakeBackend, wifi_lock_snapshot: Lock
    ) -> None:
        await schlage.set_lock_and_leave(wifi_lock_snapshot, False)
        assert fake_backend.calls == [
            ("set_setting", "__wifi_uuid__", Setting.LOCK_AND_LEAVE_ENABLED, 0)
        ]

    async def test_set_auto_lock_time(
        self, schlage: Schlage, fake_backend: FakeBackend, wifi_lock_snapshot: Lock
    ) -> None:
        await schlage.set_auto_lock_time(wifi_lock_snapshot, 300)
        assert fake_backend.calls == [
            ("set_setting", "__wifi_uuid__", Setting.AUTO_LOCK_TIME, 300)
        ]

    async def test_auto_lock_time_is_validated_before_dispatch(
        self, schlage: Schlage, fake_backend: FakeBackend, wifi_lock_snapshot: Lock
    ) -> None:
        # The allowed values are the service's, not a backend's, so the client
        # checks them before handing the write off.
        with pytest.raises(ValueError):
            await schlage.set_auto_lock_time(wifi_lock_snapshot, 17)
        assert fake_backend.calls == []

    async def test_defaults_to_the_cloud(
        self, transport: FakeTransport, wifi_lock_json: dict[str, Any]
    ) -> None:
        transport.returns(wifi_lock_json)
        schlage = Schlage(transport, USER_ID)
        await schlage.set_locked(Lock.from_json(wifi_lock_json), True)
        assert transport.request == request.put_lock_attributes(
            "__wifi_uuid__", {"lockState": 1}
        )
