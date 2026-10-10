"""The uWeave session handshake.

Four steps bring a session up, after which every record is encrypted:

1. The app writes an unencrypted connection request carrying its random nonce,
   and the lock replies with its own.
2. The app extends the lock's SAT macaroon into a session token and writes it.
   The lock's reply has to be the tag the app can compute for itself, which is
   what proves the lock holds the same secret.
3. Both sides derive the session key and id from the two nonces.
4. The app authorizes the session with a Cloud Access Token, as the first
   encrypted record.

The step 1 body is the seven CBOR items and the nonce. The byte the app calls
its connection request byte is the framing header, which
:meth:`pyschlage.ble.framing.Packetizer.connection_request` supplies, so
nothing prepends a second one.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from hmac import compare_digest
import secrets
from typing import Any, Protocol

import cbor2

from ..exceptions import BleSessionError
from . import crypto, uweave

CatMinter = Callable[[str], Awaitable[str | bytes]]
"""Mints a fresh Cloud Access Token, given the hex value the lock asked about.

:class:`pyschlage.aio.Schlage`'s transport can do this with
:func:`pyschlage.request.mint_cat`, whose response carries the new token as
hex. Returning that string is enough; bytes are accepted too.
"""

# The seven top-level CBOR items the app writes ahead of its nonce. They are
# concatenated, not wrapped in an array.
_CONNECTION_REQUEST_ITEMS = (0, 1, 0, 2, 0, 20, 2)

_CONNECTION_REQUEST_PREAMBLE = b"".join(
    cbor2.dumps(item) for item in _CONNECTION_REQUEST_ITEMS
)

# The lock's reply opens with five bytes this does not interpret. The last of
# them says whether the app must fetch a fresh CAT; the nonce follows.
_RESPONSE_HEADER_LEN = 5
_RANDOM_FLAG = 4


class RecordChannel(Protocol):
    """Carries whole uWeave records to and from a lock.

    The framing and the GATT characteristics are below this; an implementation
    deals in complete records.
    """

    async def write_connection_request(self, body: bytes) -> None:
        """Writes an app-initiated connection request, which is framed its own
        way and never fragmented.

        :param body: The request body.
        :type body: bytes
        """
        ...  # pragma: no cover

    async def write(self, record: bytes) -> None:
        """Writes a record.

        :param record: The record, already encrypted if the session is up.
        :type record: bytes
        """
        ...  # pragma: no cover

    async def read(self) -> bytes:
        """Reads the next record the lock sends.

        :rtype: bytes
        """
        ...  # pragma: no cover


def parse_connection_response(response: bytes) -> tuple[int, bytes]:
    """Splits the lock's reply to a connection request.

    :param response: The reply.
    :type response: bytes
    :return: The flag saying whether a fresh CAT is needed, and the lock's
        random nonce.
    :rtype: tuple[int, bytes]
    :raise pyschlage.exceptions.BleSessionError: When the reply is too short to
        hold a nonce.
    """
    if len(response) <= _RESPONSE_HEADER_LEN:
        raise BleSessionError(
            f"connection response is {len(response)} bytes, too short to hold a nonce"
        )
    return response[_RANDOM_FLAG], response[_RESPONSE_HEADER_LEN:]


class Session:
    """A uWeave session with a lock."""

    def __init__(
        self, channel: RecordChannel, mint_cat: CatMinter | None = None
    ) -> None:
        """Initializes a Session.

        :param channel: Carries records to and from the lock.
        :type channel: pyschlage.ble.session.RecordChannel
        :param mint_cat: Mints a fresh Cloud Access Token. Required only when
            the lock asks for one, which it does by setting a flag in its reply
            to the connection request.
        :type mint_cat: collections.abc.Callable or None
        """
        self._channel = channel
        self._mint_cat = mint_cat
        self._cipher: crypto.RecordCipher | None = None

    @property
    def is_open(self) -> bool:
        """Whether the session has been established."""
        return self._cipher is not None

    async def open(self, sat: str | bytes, cat: str | bytes) -> None:
        """Runs the handshake.

        :param sat: The lock's SAT macaroon, as the hex the cloud service
            reports or as the bytes it decodes to.
        :type sat: str or bytes
        :param cat: The lock's Cloud Access Token, in the same form. Ignored
            when the lock asks for a freshly minted one.
        :type cat: str or bytes
        :raise pyschlage.exceptions.BleSessionError: When the lock's reply does
            not verify, or when it asks for a CAT that cannot be minted.
        :raise pyschlage.exceptions.UWeaveError: When the lock rejects the
            authorization.
        """
        sat_bytes = crypto.decode_token(sat)
        cat_bytes = crypto.decode_token(cat)

        client_random = secrets.token_bytes(crypto.RANDOM_LEN)
        await self._channel.write_connection_request(
            _CONNECTION_REQUEST_PREAMBLE + client_random
        )
        flag, server_random = parse_connection_response(await self._channel.read())

        record, sat_tag = crypto.extend_sat(sat_bytes, client_random, server_random)
        await self._channel.write(record)
        reply = await self._channel.read()
        expected = crypto.session_tag(sat_tag, 2, client_random, server_random)
        if not compare_digest(reply, expected):
            # The lock could not produce the tag, so it does not hold the
            # secret the SAT was issued against. Do not continue.
            raise BleSessionError("the lock's handshake reply did not verify")

        if flag:
            if self._mint_cat is None:
                raise BleSessionError(
                    "the lock asked for a freshly minted CAT, but no minter "
                    "was supplied"
                )
            cat_bytes = crypto.decode_token(
                await self._mint_cat((bytes([flag]) + server_random).hex())
            )

        session_key, session_id = crypto.derive_session(
            client_random, server_random, sat_tag
        )
        self._cipher = crypto.RecordCipher(session_key, session_id)
        await self.call(uweave.authorize_cat(cat_bytes))

    async def call(self, record: bytes) -> Any:
        """Sends a record and returns the payload of the lock's reply.

        Every trait reply nests its payload one level inside the envelope's
        result, writes as well as reads, so this unwraps it.

        The test for that nesting is "key 17 is present", which is ambiguous in
        general: :data:`pyschlage.ble.uweave.RESULT` and
        :data:`pyschlage.ble.uweave.REPORT_OPERATING_MODE` are both ``17``, so
        a bare report carrying an operating mode would be unwrapped as though
        it were an envelope. It is safe here because no trait reply is a bare
        report. The one call whose reply is shaped differently, the lock-state
        read, goes through :meth:`read_lock_state` instead.

        :param record: The plaintext CBOR record to send.
        :type record: bytes
        :raise pyschlage.exceptions.BleSessionError: When the session is not
            open.
        :raise pyschlage.exceptions.UWeaveError: When the lock reports a
            failure.
        """
        result = await self._exchange(record)
        if isinstance(result, dict) and uweave.RESULT in result:
            return result[uweave.RESULT]
        return result

    async def _exchange(self, record: bytes) -> Any:
        """Sends a record and returns the result of the reply's envelope.

        This is :meth:`call` without the unwrap, for the one reply whose
        payload is not nested a second time under
        :data:`pyschlage.ble.uweave.RESULT`.
        """
        if self._cipher is None:
            raise BleSessionError("the session is not open")
        await self._channel.write(self._cipher.encrypt(record))
        reply = self._cipher.decrypt(await self._channel.read())
        return uweave.decode_response(reply)

    async def read_lock_state(self) -> Any:
        """Reads the lock's current state.

        :return: The lock-state report, keyed by the ``REPORT_*`` constants in
            :mod:`pyschlage.ble.uweave`.
        :raise pyschlage.exceptions.BleSessionError: When the session is not
            open.
        :raise pyschlage.exceptions.UWeaveError: When the lock reports a
            failure, or when its reply is not shaped like a lock-state reply.
        """
        return uweave.lock_state_report(await self._exchange(uweave.read_lock_state()))

    async def set_locked(self, locked: bool, user_id: str) -> Any:
        """Locks or unlocks the lock.

        :param locked: True to lock, False to unlock.
        :type locked: bool
        :param user_id: The account making the change, which the lock records.
        :type user_id: str
        :raise pyschlage.exceptions.BleSessionError: When the session is not
            open.
        :raise pyschlage.exceptions.UWeaveError: When the lock reports a
            failure.
        """
        return await self.call(uweave.set_locked(locked, user_id))

    async def write_trait(
        self, trait: int, attribute: int, value: Any, user_id: str
    ) -> Any:
        """Writes one attribute of a trait.

        :param trait: The trait to write, e.g.
            :data:`pyschlage.ble.uweave.TRAIT_LOCK_CONFIG`.
        :type trait: int
        :param attribute: The attribute of that trait.
        :type attribute: int
        :param value: The value to write.
        :param user_id: The account making the change, which the lock records.
        :type user_id: str
        :raise pyschlage.exceptions.BleSessionError: When the session is not
            open.
        :raise pyschlage.exceptions.UWeaveError: When the lock reports a
            failure.
        """
        return await self.call(uweave.write_trait(trait, attribute, value, user_id))

    async def read_trait(
        self, trait: int, attribute: int, method_id: int = uweave.METHOD_GET
    ) -> Any:
        """Reads one attribute of a trait.

        :param trait: The trait to read, e.g.
            :data:`pyschlage.ble.uweave.TRAIT_LOCK_DATA`.
        :type trait: int
        :param attribute: The attribute of that trait.
        :type attribute: int
        :param method_id: The method to call. The default suits a trait read;
            the lock config group's scalar reads use
            :data:`pyschlage.ble.uweave.METHOD_ADD` instead.
        :type method_id: int
        :raise pyschlage.exceptions.BleSessionError: When the session is not
            open.
        :raise pyschlage.exceptions.UWeaveError: When the lock reports a
            failure.
        """
        return await self.call(uweave.read_trait(trait, attribute, method_id))
