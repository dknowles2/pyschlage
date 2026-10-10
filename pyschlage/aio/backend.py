"""How the library reaches a lock to change it."""

from __future__ import annotations

from dataclasses import replace
from enum import Enum
from typing import Any, Protocol

from .. import request
from ..device import LockState
from .lock import Lock
from .transport import Transport


class Setting(Enum):
    """A lock setting that can be written over any transport.

    Each backend knows how to address these for itself: the cloud service
    takes a named device attribute, while a lock reached over Bluetooth LE
    takes a numbered attribute of a trait.
    """

    BEEPER_ENABLED = "beeper_enabled"
    """Whether the keypress beep is enabled."""

    LOCK_AND_LEAVE_ENABLED = "lock_and_leave_enabled"
    """Whether lock-and-leave (a.k.a. "1-Touch Locking") is enabled."""

    AUTO_LOCK_TIME = "auto_lock_time"
    """Seconds of inactivity before the lock locks itself."""


class LockBackend(Protocol):
    """How the library reaches a lock to change it.

    The cloud service is one way to reach a lock; a direct Bluetooth LE
    connection is another. Both take and return snapshots, so a caller cannot
    tell from the result which way it went.

    Only the operations every backend can carry out live here. Access codes,
    logs, users and notifications are cloud-only, and stay on
    :class:`pyschlage.aio.Schlage`.
    """

    async def set_locked(self, lock: Lock, locked: bool) -> Lock:
        """Locks or unlocks the device.

        :param lock: The lock to operate.
        :type lock: pyschlage.aio.Lock
        :param locked: True to lock, False to unlock.
        :type locked: bool
        :rtype: pyschlage.aio.Lock
        """
        ...  # pragma: no cover

    async def set_setting(self, lock: Lock, setting: Setting, value: int) -> Lock:
        """Writes one of a lock's settings.

        :param lock: The lock to modify.
        :type lock: pyschlage.aio.Lock
        :param setting: Which setting to write.
        :type setting: pyschlage.aio.Setting
        :param value: The value to write.
        :type value: int
        :rtype: pyschlage.aio.Lock
        """
        ...  # pragma: no cover


# The device attribute each setting is called in the cloud service's JSON.
_CLOUD_ATTRIBUTES = {
    Setting.BEEPER_ENABLED: "beeperEnabled",
    Setting.LOCK_AND_LEAVE_ENABLED: "lockAndLeaveEnabled",
    Setting.AUTO_LOCK_TIME: "autoLockTime",
}


class CloudBackend:
    """A :class:`LockBackend` that reaches locks through the cloud service."""

    def __init__(self, transport: Transport, user_id: str) -> None:
        """Initializes a CloudBackend.

        :param transport: Transport used to issue requests.
        :type transport: pyschlage.aio.Transport
        :param user_id: The unique id of the authenticated user, which the
            service records against a change made through a bridge.
        :type user_id: str
        """
        self._transport = transport
        self._user_id = user_id

    async def set_locked(self, lock: Lock, locked: bool) -> Lock:
        """Locks or unlocks the device.

        :param lock: The lock to operate.
        :type lock: pyschlage.aio.Lock
        :param locked: True to lock, False to unlock.
        :type locked: bool
        :rtype: pyschlage.aio.Lock
        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        lock_state = int(LockState.LOCKED if locked else LockState.UNLOCKED)
        if lock.is_wifi_lock:
            return await self._put_attributes(lock, {"lockState": lock_state})

        # Bridge-attached locks take a command instead, and the response
        # carries no device state, so the returned Lock reflects what we asked
        # for rather than what the lock reported. Call get_lock() to confirm.
        await self._transport.send(
            request.change_lock_state(
                lock.device_id,
                cat=lock._cat,
                user_id=self._user_id,
                lock_state=lock_state,
            )
        )
        return replace(lock, is_locked=locked, is_jammed=False)

    async def set_setting(self, lock: Lock, setting: Setting, value: int) -> Lock:
        """Writes one of a lock's settings.

        :param lock: The lock to modify.
        :type lock: pyschlage.aio.Lock
        :param setting: Which setting to write.
        :type setting: pyschlage.aio.Setting
        :param value: The value to write.
        :type value: int
        :rtype: pyschlage.aio.Lock
        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        return await self._put_attributes(lock, {_CLOUD_ATTRIBUTES[setting]: value})

    async def _put_attributes(self, lock: Lock, attributes: dict[str, Any]) -> Lock:
        resp = await self._transport.send(
            request.put_lock_attributes(lock.device_id, attributes)
        )
        return Lock.from_json(resp)
