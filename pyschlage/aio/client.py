"""Asynchronous API for interacting with the Schlage WiFi cloud service."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Self

import aiohttp

from .. import request
from ..auth import Auth
from ..lock import AUTO_LOCK_TIMES
from ..log import LockLog
from ..notification import ON_UNLOCK_ACTION, id_for_access_code
from ..request import (
    ADD_ACCESS_CODE,
    DELETE_ACCESS_CODE,
    UPDATE_ACCESS_CODE,
)
from ..user import User
from .backend import CloudBackend, LockBackend, Setting
from .code import AccessCode, NewAccessCode
from .lock import Lock
from .notification import Notification
from .transport import AiohttpTransport, Transport


def _device_id(lock: Lock | str) -> str:
    return lock if isinstance(lock, str) else lock.device_id


class Schlage:
    """Asynchronous API for interacting with the Schlage WiFi cloud service.

    All state is returned as immutable snapshots. Methods that change a lock
    return the updated :class:`pyschlage.aio.Lock` rather than mutating the one
    passed in.
    """

    def __init__(
        self,
        transport: Transport,
        user_id: str,
        *,
        backend: LockBackend | None = None,
        _owned_session: aiohttp.ClientSession | None = None,
    ) -> None:
        """Instantiates a Schlage API object.

        Prefer :func:`pyschlage.aio.connect` or :meth:`authenticate`; this
        constructor is for tests and custom transports.

        :param transport: Transport used to issue requests.
        :type transport: pyschlage.aio.Transport
        :param user_id: The unique id of the authenticated user.
        :type user_id: str
        :param backend: How to reach a lock to change it. Defaults to the
            cloud service.
        :type backend: pyschlage.aio.LockBackend or None
        """
        self._transport = transport
        self._user_id = user_id
        self._backend = backend or CloudBackend(transport, user_id)
        self._owned_session = _owned_session

    @classmethod
    async def authenticate(
        cls,
        username: str,
        password: str,
        *,
        session: aiohttp.ClientSession | None = None,
    ) -> Schlage:
        """Authenticates and returns a ready-to-use API object.

        :param username: The username associated with the Schlage account.
        :type username: str
        :param password: The password for the account.
        :type password: str
        :param session: An existing aiohttp session to issue requests on. If
            omitted, one is created and closed by :meth:`close`.
        :type session: aiohttp.ClientSession or None
        :rtype: pyschlage.aio.Schlage
        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        owned_session = None
        if session is None:
            owned_session = session = aiohttp.ClientSession()
        try:
            transport = AiohttpTransport(Auth(username, password), session)
            user_id = await cls._fetch_user_id(transport)
        except BaseException:
            if owned_session is not None:
                await owned_session.close()
            raise
        return cls(transport, user_id, _owned_session=owned_session)

    @classmethod
    async def from_transport(cls, transport: Transport) -> Schlage:
        """Returns an API object using an already-configured transport.

        :param transport: Transport used to issue requests.
        :type transport: pyschlage.aio.Transport
        :rtype: pyschlage.aio.Schlage
        """
        return cls(transport, await cls._fetch_user_id(transport))

    @staticmethod
    async def _fetch_user_id(transport: Transport) -> str:
        resp = await transport.send(request.get_current_user())
        return resp["identityId"]

    @property
    def user_id(self) -> str:
        """The unique id of the authenticated user."""
        return self._user_id

    async def close(self) -> None:
        """Closes the underlying session, if this object created one."""
        if self._owned_session is not None:
            await self._owned_session.close()
            self._owned_session = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    # -- Locks and users ---------------------------------------------------

    async def get_locks(self) -> list[Lock]:
        """Retrieves all locks associated with this account.

        :rtype: list[pyschlage.aio.Lock]
        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        resp = await self._transport.send(request.get_locks())
        return [Lock.from_json(lock_json) for lock_json in resp]

    async def get_lock(self, lock: Lock | str) -> Lock:
        """Fetches the current state of a single lock.

        :param lock: The lock, or its device id.
        :type lock: pyschlage.aio.Lock or str
        :rtype: pyschlage.aio.Lock
        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        resp = await self._transport.send(request.get_lock(_device_id(lock)))
        return Lock.from_json(resp)

    async def get_users(self) -> list[User]:
        """Retrieves all users associated with this account's locks.

        :rtype: list[pyschlage.user.User]
        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        resp = await self._transport.send(request.get_users())
        return [User.from_json(user_json) for user_json in resp]

    # -- Lock state and settings -------------------------------------------

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
        return await self._backend.set_locked(lock, locked)

    async def set_beeper(self, lock: Lock, enabled: bool) -> Lock:
        """Sets the beeper_enabled setting.

        :param lock: The lock to modify.
        :type lock: pyschlage.aio.Lock
        :param enabled: Whether the keypress beep should be enabled.
        :type enabled: bool
        :rtype: pyschlage.aio.Lock
        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        return await self._backend.set_setting(
            lock, Setting.BEEPER_ENABLED, int(enabled)
        )

    async def set_lock_and_leave(self, lock: Lock, enabled: bool) -> Lock:
        """Sets the lock_and_leave setting.

        :param lock: The lock to modify.
        :type lock: pyschlage.aio.Lock
        :param enabled: Whether lock-and-leave should be enabled.
        :type enabled: bool
        :rtype: pyschlage.aio.Lock
        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        return await self._backend.set_setting(
            lock, Setting.LOCK_AND_LEAVE_ENABLED, int(enabled)
        )

    async def set_auto_lock_time(self, lock: Lock, auto_lock_time: int) -> Lock:
        """Sets the auto_lock_time setting. Setting it to ``0`` turns off the
        auto-lock feature.

        :param lock: The lock to modify.
        :type lock: pyschlage.aio.Lock
        :param auto_lock_time: Number of seconds of inactivity before the lock
            automatically locks itself. Must be one of
            :data:`pyschlage.lock.AUTO_LOCK_TIMES`.
        :type auto_lock_time: int
        :rtype: pyschlage.aio.Lock
        :raise ValueError: When auto_lock_time is not one of AUTO_LOCK_TIMES.
        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        if auto_lock_time not in AUTO_LOCK_TIMES:
            raise ValueError(f"auto_lock_time must be one of: {AUTO_LOCK_TIMES}")
        return await self._backend.set_setting(
            lock, Setting.AUTO_LOCK_TIME, auto_lock_time
        )

    # -- Logs --------------------------------------------------------------

    async def get_logs(
        self,
        lock: Lock | str,
        *,
        limit: int | None = None,
        sort_desc: bool = False,
    ) -> list[LockLog]:
        """Fetches activity logs for the lock.

        :param lock: The lock, or its device id.
        :type lock: pyschlage.aio.Lock or str
        :param limit: The number of log entries to return.
        :type limit: int or None
        :param sort_desc: Whether to sort entries in descending order.
        :type sort_desc: bool
        :rtype: list[pyschlage.log.LockLog]
        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        resp = await self._transport.send(
            request.get_logs(_device_id(lock), limit=limit, sort_desc=sort_desc)
        )
        return [LockLog.from_json(log_json) for log_json in resp]

    async def keypad_disabled(self, lock: Lock | str) -> bool:
        """Fetches recent logs and reports whether the keypad is disabled.

        :param lock: The lock, or its device id.
        :type lock: pyschlage.aio.Lock or str
        :rtype: bool
        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        return Lock.keypad_disabled(await self.get_logs(lock))

    # -- Access codes ------------------------------------------------------

    async def get_access_codes(self, lock: Lock) -> list[AccessCode]:
        """Fetches the access codes for a lock.

        :param lock: The lock to fetch codes for.
        :type lock: pyschlage.aio.Lock
        :rtype: list[pyschlage.aio.AccessCode]
        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        notifications = await self._get_access_code_notifications(lock.device_id)
        resp = await self._transport.send(request.get_access_codes(lock.device_id))
        return [
            AccessCode.from_json(
                code_json,
                device_id=lock.device_id,
                device_type=lock.device_type,
                notification=notifications.get(code_json["accesscodeId"]),
            )
            for code_json in resp
        ]

    async def add_access_code(self, lock: Lock, code: NewAccessCode) -> AccessCode:
        """Adds an access code to the lock.

        :param lock: The lock to add the code to.
        :type lock: pyschlage.aio.Lock
        :param code: The access code to add.
        :type code: pyschlage.aio.NewAccessCode
        :rtype: pyschlage.aio.AccessCode
        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        resp = await self._transport.send(
            request.send_command(lock.device_id, ADD_ACCESS_CODE, code.to_json())
        )
        # The service echoes back only the new id, so the returned AccessCode
        # is assembled from what we sent.
        added = AccessCode(
            access_code_id=resp["accesscodeId"],
            device_id=lock.device_id,
            device_type=lock.device_type,
            name=code.name,
            code=code.code,
            schedule=code.schedule,
            notify_on_use=code.notify_on_use,
            disabled=code.disabled,
        )
        await self._save_access_code_notification(added)
        return added

    async def update_access_code(self, code: AccessCode) -> AccessCode:
        """Commits changes to an existing access code.

        Build the modified code with :func:`dataclasses.replace`.

        :param code: The access code to update.
        :type code: pyschlage.aio.AccessCode
        :rtype: pyschlage.aio.AccessCode
        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        await self._transport.send(
            request.send_command(code.device_id, UPDATE_ACCESS_CODE, code.to_json())
        )
        await self._save_access_code_notification(code)
        return code

    async def delete_access_code(self, code: AccessCode) -> None:
        """Deletes an access code.

        :param code: The access code to delete.
        :type code: pyschlage.aio.AccessCode
        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        await self._transport.send(
            request.send_command(code.device_id, DELETE_ACCESS_CODE, code.to_json())
        )
        if code._notification is not None:
            await self._transport.send(
                request.delete_notification(code._notification.notification_id)
            )

    # -- Internals ---------------------------------------------------------

    async def _get_access_code_notifications(
        self, device_id: str
    ) -> dict[str, Notification]:
        """Returns on-unlock notifications for this user, keyed by access code id.

        Access codes and the notifications that fire when they are used are
        separate resources, associated only by the notification's id.
        """
        resp = await self._transport.send(request.get_notifications(device_id))
        prefix = id_for_access_code(self._user_id, "")
        notifications = {}
        for notification_json in resp:
            notification = Notification.from_json(notification_json)
            if notification.notification_type != ON_UNLOCK_ACTION:
                continue
            if not notification.notification_id.startswith(prefix):
                continue
            access_code_id = notification.notification_id.removeprefix(prefix)
            notifications[access_code_id] = notification
        return notifications

    async def _save_access_code_notification(self, code: AccessCode) -> None:
        existing = code._notification
        notification = Notification(
            notification_id=id_for_access_code(self._user_id, code.access_code_id),
            user_id=self._user_id,
            device_id=code.device_id,
            device_type=code.device_type,
            notification_type=ON_UNLOCK_ACTION,
            active=code.notify_on_use,
            filter_value=code.name,
        )
        # An existing notification is updated in place; a new one is created.
        exists = existing is not None and existing.created_at is not None
        await self._transport.send(
            request.save_notification(
                code.device_id, notification.to_json(), exists=exists
            )
        )


@asynccontextmanager
async def connect(
    username: str,
    password: str,
    *,
    session: aiohttp.ClientSession | None = None,
) -> AsyncIterator[Schlage]:
    """Authenticates and yields a :class:`Schlage` client, closing it on exit.

    .. code-block:: python

        async with pyschlage.aio.connect("username", "password") as schlage:
            locks = await schlage.get_locks()

    :param username: The username associated with the Schlage account.
    :type username: str
    :param password: The password for the account.
    :type password: str
    :param session: An existing aiohttp session to issue requests on. If
        omitted, one is created and closed on exit.
    :type session: aiohttp.ClientSession or None
    :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
    :raise pyschlage.exceptions.UnknownError: On other errors.
    """
    client = await Schlage.authenticate(username, password, session=session)
    try:
        yield client
    finally:
        await client.close()
