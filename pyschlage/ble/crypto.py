"""Cryptography for the uWeave BLE session.

The constructions are reproduced as the app performs them. None of it has been
exercised against a real lock; where the app's own behavior is unsafe, this
module refuses rather than copying it.
"""

from __future__ import annotations

from dataclasses import dataclass
import io
from typing import Any

import cbor2
from Crypto.Cipher import AES
from Crypto.Hash import HMAC, SHA256
from Crypto.Protocol.KDF import HKDF

from ..exceptions import BleSessionError

APP_TO_LOCK = 0x01
"""Direction byte of a record the app sends."""

LOCK_TO_APP = 0x03
"""Direction byte of a record the lock sends."""

MAC_LEN = 12
"""Length of a record's EAX tag: 96 bits."""

SESSION_KEY_LEN = 16
"""Length of the AES-128 session key."""

RANDOM_LEN = 12
"""Length of the random nonce each side contributes to the handshake."""

TAG_LEN = 16
"""Length of a macaroon tag: HMAC-SHA256 truncated."""

_MAX_COUNTER = 0xFF
_SESSION_CAVEAT = 0x14
_HKDF_LEN = 32
_HKDF_INFO = b"session key"

# Hardcoded in the app, in SenseBlePeripheral.generateSessionData.
_HKDF_SALT = bytes(
    (
        0x00, 0x8A, 0x39, 0x36, 0x22, 0x04, 0x1F, 0x5F,
        0x0F, 0xC7, 0x5D, 0x97, 0xDA, 0xEE, 0x6E, 0x81,
        0xCB, 0xBB, 0x2B, 0xC7, 0x4F, 0x9C, 0xCC, 0x91,
        0xE7, 0x5E, 0x77, 0xA5, 0x6B, 0x4A, 0x4B, 0x05,
    )
)  # fmt: skip


@dataclass
class Macaroon:
    """A macaroon: a list of caveats and an HMAC tag over them."""

    caveats: list[Any]
    """The caveats, in the order they were added."""

    tag: bytes
    """The HMAC-SHA256 tag, truncated to :data:`TAG_LEN`."""

    @classmethod
    def decode(cls, data: bytes) -> Macaroon:
        """Decodes a macaroon from its CBOR representation.

        The caveats and the tag are two items written one after the other, not
        an array holding both. The whole thing arrives wrapped in an outer byte
        string from the cloud service, which this unwraps.

        :param data: The CBOR-encoded macaroon.
        :type data: bytes
        :rtype: pyschlage.ble.crypto.Macaroon
        :raise pyschlage.exceptions.BleSessionError: When the representation is
            not a macaroon.
        """
        decoder = cbor2.CBORDecoder(io.BytesIO(data))
        first = decoder.decode()
        if isinstance(first, bytes):
            # An outer byte string holding the real representation.
            return cls.decode(first)
        if not isinstance(first, list):
            raise BleSessionError(
                f"macaroon starts with {type(first).__name__}, expected caveats"
            )
        tag = decoder.decode()
        if not isinstance(tag, bytes):
            raise BleSessionError(
                f"macaroon tag is {type(tag).__name__}, expected bytes"
            )
        return cls(caveats=list(first), tag=tag)

    def encode(self) -> bytes:
        """Returns the CBOR representation of this macaroon.

        The caveats and the tag go out as two top-level items, which is what
        the lock expects; an array holding both would not decode.

        :rtype: bytes
        """
        return cbor2.dumps(self.caveats) + cbor2.dumps(self.tag)


def decode_token(value: str | bytes) -> bytes:
    """Decodes a SAT or CAT as the cloud service reports it.

    The tokens are hex, which the app converts a nibble pair at a time. Bytes
    pass through, so a caller holding an already-decoded token need not care.

    :param value: The token, as hex or as the bytes it decodes to.
    :type value: str or bytes
    :rtype: bytes
    :raise ValueError: When the string is not hex.
    """
    if isinstance(value, bytes):
        return value
    return bytes.fromhex(value)


def session_tag(
    sat_tag: bytes, index: int, client_random: bytes, server_random: bytes
) -> bytes:
    """Returns the handshake tag for the given step.

    The app mints these with the SAT's own tag as the HMAC key. Index 1 is the
    tag the app sends with its extended SAT; index 2 is what the lock must
    reply with for the handshake to be trusted.

    :param sat_tag: The tag of the SAT macaroon, used as the HMAC key.
    :type sat_tag: bytes
    :param index: Which tag to mint.
    :type index: int
    :param client_random: The random bytes the app contributed.
    :type client_random: bytes
    :param server_random: The random bytes the lock contributed.
    :type server_random: bytes
    :rtype: bytes
    """
    inner = cbor2.dumps(bytes([index]) + client_random + server_random)
    outer = cbor2.dumps(bytes([_SESSION_CAVEAT]) + inner)
    return HMAC.new(sat_tag, outer, SHA256).digest()[:TAG_LEN]


def extend_sat(
    sat: bytes, client_random: bytes, server_random: bytes
) -> tuple[bytes, bytes]:
    """Extends a SAT macaroon into a session token.

    :param sat: The SAT from the lock's cloud attributes, decoded to bytes.
    :type sat: bytes
    :param client_random: The random bytes the app contributed.
    :type client_random: bytes
    :param server_random: The random bytes the lock contributed.
    :type server_random: bytes
    :return: The record to write, and the original SAT tag, which keys the rest
        of the handshake.
    :rtype: tuple[bytes, bytes]
    """
    macaroon = Macaroon.decode(sat)
    sat_tag = macaroon.tag
    macaroon.caveats.append(bytes([_SESSION_CAVEAT]))
    macaroon.tag = session_tag(sat_tag, 1, client_random, server_random)
    return cbor2.dumps(macaroon.encode()), sat_tag


def derive_session(
    client_random: bytes, server_random: bytes, sat_tag: bytes
) -> tuple[bytes, bytes]:
    """Derives the session key and id from the handshake.

    :param client_random: The random bytes the app contributed.
    :type client_random: bytes
    :param server_random: The random bytes the lock contributed.
    :type server_random: bytes
    :param sat_tag: The tag of the SAT macaroon.
    :type sat_tag: bytes
    :return: The AES-128 session key and the 16-byte session id that prefixes
        every record nonce.
    :rtype: tuple[bytes, bytes]
    """
    ikm = bytes([2]) + client_random + server_random + sat_tag
    okm = HKDF(ikm, _HKDF_LEN, _HKDF_SALT, SHA256, context=_HKDF_INFO)
    assert isinstance(okm, bytes)  # One key, so not a list.
    return okm[:SESSION_KEY_LEN], okm[SESSION_KEY_LEN:]


def record_nonce(session_id: bytes, direction: int, counter: int) -> bytes:
    """Returns the EAX nonce for a record.

    :param session_id: The session id from :func:`derive_session`.
    :type session_id: bytes
    :param direction: :data:`APP_TO_LOCK` or :data:`LOCK_TO_APP`.
    :type direction: int
    :param counter: The record counter for that direction.
    :type counter: int
    :rtype: bytes
    """
    return session_id + bytes([direction, 0x00, 0x00, counter])


class RecordCipher:
    """Encrypts and decrypts session records.

    Each direction has its own counter, starting at 1 and incrementing per
    record.

    There is deliberately no way to restart the counters. A reconnect means a
    new handshake and a new key, so :class:`pyschlage.ble.session.Session`
    builds a fresh cipher; restarting them under a key that is still live would
    repeat EAX nonces, which leaks the xor of the two plaintexts and undermines
    the tag.
    """

    def __init__(self, session_key: bytes, session_id: bytes) -> None:
        """Initializes a RecordCipher.

        :param session_key: The AES-128 session key.
        :type session_key: bytes
        :param session_id: The session id prefixing every record nonce.
        :type session_id: bytes
        """
        self._key = session_key
        self._session_id = session_id
        self._counters = {APP_TO_LOCK: 1, LOCK_TO_APP: 1}

    def _next_nonce(self, direction: int) -> bytes:
        counter = self._counters[direction]
        if counter > _MAX_COUNTER:
            # A record counter is one byte of the nonce. The app truncates and
            # carries on, which repeats a nonce under a live key; refuse
            # instead. Recovery is a fresh handshake, deriving a new key and
            # session id, not a restart of the counters.
            raise ValueError(
                f"record counter for direction {direction:#x} overflowed; "
                "open a new session to continue"
            )
        self._counters[direction] = counter + 1
        return record_nonce(self._session_id, direction, counter)

    def encrypt(self, record: bytes) -> bytes:
        """Encrypts a record to send to the lock.

        :param record: The CBOR-encoded record.
        :type record: bytes
        :return: The ciphertext with its tag appended.
        :rtype: bytes
        :raise ValueError: When the record counter has overflowed.
        """
        nonce = self._next_nonce(APP_TO_LOCK)
        cipher = AES.new(self._key, AES.MODE_EAX, nonce=nonce, mac_len=MAC_LEN)
        ciphertext, tag = cipher.encrypt_and_digest(record)
        return ciphertext + tag

    def decrypt(self, data: bytes) -> bytes:
        """Decrypts a record received from the lock.

        :param data: The ciphertext with its tag appended.
        :type data: bytes
        :rtype: bytes
        :raise ValueError: When the data is too short to hold a tag, when the
            tag does not verify, or when the record counter has overflowed.
        """
        if len(data) < MAC_LEN:
            raise ValueError(f"record is shorter than its {MAC_LEN}-byte tag")
        nonce = self._next_nonce(LOCK_TO_APP)
        cipher = AES.new(self._key, AES.MODE_EAX, nonce=nonce, mac_len=MAC_LEN)
        return cipher.decrypt_and_verify(data[:-MAC_LEN], data[-MAC_LEN:])
