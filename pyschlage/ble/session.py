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

One ambiguity is worth naming. ``PROTOCOL.md`` describes the step 1 body as a
"connection_request_byte", then seven CBOR items, then the nonce. Its framing
section separately says an app-initiated connection request is a header byte
followed by the raw body. This module reads those as the same byte, so the
body here is the CBOR items and the nonce, and the header comes from
:meth:`pyschlage.ble.framing.Packetizer.connection_request`. If that reading
is wrong, step 1 is off by one leading byte.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from hmac import compare_digest
import secrets
from typing import Any, Protocol

import cbor2

from ..exceptions import BleSessionError
from . import crypto, uweave

CatMinter = Callable[[str], Awaitable[bytes]]
"""Mints a fresh Cloud Access Token, given the hex value the lock asked about.

:class:`pyschlage.aio.Schlage`'s transport can do this with
:func:`pyschlage.request.mint_cat`.
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
        self._request_id = 0

    @property
    def is_open(self) -> bool:
        """Whether the session has been established."""
        return self._cipher is not None

    def _next_request_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def open(self, sat: bytes, cat: bytes) -> None:
        """Runs the handshake.

        :param sat: The lock's SAT macaroon, decoded to bytes.
        :type sat: bytes
        :param cat: The lock's Cloud Access Token, decoded to bytes. Ignored
            when the lock asks for a freshly minted one.
        :type cat: bytes
        :raise pyschlage.exceptions.BleSessionError: When the lock's reply does
            not verify, or when it asks for a CAT that cannot be minted.
        :raise pyschlage.exceptions.UWeaveError: When the lock rejects the
            authorization.
        """
        client_random = secrets.token_bytes(crypto.RANDOM_LEN)
        await self._channel.write_connection_request(
            _CONNECTION_REQUEST_PREAMBLE + client_random
        )
        flag, server_random = parse_connection_response(await self._channel.read())

        record, sat_tag = crypto.extend_sat(sat, client_random, server_random)
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
            cat = await self._mint_cat((bytes([flag]) + server_random).hex())

        session_key, session_id = crypto.derive_session(
            client_random, server_random, sat_tag
        )
        self._cipher = crypto.RecordCipher(session_key, session_id)
        await self.call(uweave.authorize_cat(cat, self._next_request_id()))

    async def call(self, record: bytes) -> Any:
        """Sends a record and returns the result of the lock's reply.

        :param record: The plaintext CBOR record to send.
        :type record: bytes
        :raise pyschlage.exceptions.BleSessionError: When the session is not
            open.
        :raise pyschlage.exceptions.UWeaveError: When the lock reports a
            failure.
        """
        if self._cipher is None:
            raise BleSessionError("the session is not open")
        await self._channel.write(self._cipher.encrypt(record))
        reply = self._cipher.decrypt(await self._channel.read())
        return uweave.decode_response(reply)

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
        return await self.call(
            uweave.set_locked(locked, user_id, self._next_request_id())
        )

    async def read_trait(self, trait: int, attribute: int) -> Any:
        """Reads one attribute of a trait.

        A trait read nests its payload one level deeper than the envelope's
        result, so this unwraps it.

        :param trait: The trait to read, e.g. :data:`pyschlage.ble.uweave.TRAIT_LOCK_DATA`.
        :type trait: int
        :param attribute: The attribute of that trait.
        :type attribute: int
        :raise pyschlage.exceptions.BleSessionError: When the session is not
            open.
        :raise pyschlage.exceptions.UWeaveError: When the lock reports a
            failure.
        """
        result = await self.call(
            uweave.read_trait(trait, attribute, self._next_request_id())
        )
        if isinstance(result, dict):
            return result.get(uweave.RESULT)
        return result
