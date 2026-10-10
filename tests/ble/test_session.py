"""Tests for the uWeave session handshake."""

from typing import Any

import cbor2
from Crypto.Cipher import AES
import pytest

from pyschlage.ble import crypto, session, uweave
from pyschlage.exceptions import BleSessionError, UWeaveError

SAT_TAG = bytes(range(32, 32 + crypto.TAG_LEN))
SERVER_RANDOM = bytes(range(100, 100 + crypto.RANDOM_LEN))
CAT = b"\xca\xfe"
USER_ID = "8b1a9953-c461-1296-a827-abf8c47804d7"


def sat() -> bytes:
    macaroon = crypto.Macaroon(caveats=[b"\x01"], tag=SAT_TAG)
    return cbor2.dumps(macaroon.encode())


class FakeLock:
    """A RecordChannel that plays a scripted lock.

    It holds the other end of the session: it derives the same key, decrypts
    what the app sends, and encrypts its replies with the lock-to-app
    direction, so the app's own cipher is exercised rather than mirrored.
    """

    def __init__(self, *, random_flag: int = 0, bad_handshake: bool = False) -> None:
        self.random_flag = random_flag
        self.bad_handshake = bad_handshake
        self.connection_requests: list[bytes] = []
        self.writes: list[bytes] = []
        self.plaintexts: list[bytes] = []
        self.queued: list[Any] = []
        self.queued_envelopes: list[Any] = []
        self._replies: list[bytes] = []
        self._client_random = b""
        self._key = b""
        self._session_id = b""
        self._to_lock = 1
        self._to_app = 1

    def replies_with(self, *payloads: Any) -> None:
        """Queues the payloads the lock will answer calls with.

        Each is wrapped in the envelope and its nested result, as the lock
        sends it.
        """
        self.queued.extend(payloads)

    async def write_connection_request(self, body: bytes) -> None:
        self.connection_requests.append(body)
        self._client_random = body[-crypto.RANDOM_LEN :]
        self._replies.append(bytes(4) + bytes([self.random_flag]) + SERVER_RANDOM)

    def replies_with_envelope(self, *envelopes: Any) -> None:
        """Queues whole envelopes, for a reply that is not a trait reply."""
        self.queued_envelopes.extend(envelopes)

    async def write(self, record: bytes) -> None:
        self.writes.append(record)
        if not self._key:
            self._handshake()
            return
        self.plaintexts.append(self._decrypt(record))
        if self.queued_envelopes:
            reply = self.queued_envelopes.pop(0)
        else:
            # Every trait reply nests its payload inside the result.
            payload = self.queued.pop(0) if self.queued else {}
            reply = {1: 8, 2: uweave.METHOD_SET, 17: {17: payload}}
        self._replies.append(self._encrypt(cbor2.dumps(reply)))

    async def read(self) -> bytes:
        return self._replies.pop(0)

    def _handshake(self) -> None:
        if self.bad_handshake:
            self._replies.append(bytes(crypto.TAG_LEN))
            return
        self._replies.append(
            crypto.session_tag(SAT_TAG, 2, self._client_random, SERVER_RANDOM)
        )
        self._key, self._session_id = crypto.derive_session(
            self._client_random, SERVER_RANDOM, SAT_TAG
        )

    def _cipher(self, direction: int, counter: int) -> Any:
        nonce = crypto.record_nonce(self._session_id, direction, counter)
        return AES.new(self._key, AES.MODE_EAX, nonce=nonce, mac_len=crypto.MAC_LEN)

    def _decrypt(self, record: bytes) -> bytes:
        cipher = self._cipher(crypto.APP_TO_LOCK, self._to_lock)
        self._to_lock += 1
        return cipher.decrypt_and_verify(
            record[: -crypto.MAC_LEN], record[-crypto.MAC_LEN :]
        )

    def _encrypt(self, record: bytes) -> bytes:
        cipher = self._cipher(crypto.LOCK_TO_APP, self._to_app)
        self._to_app += 1
        ciphertext, tag = cipher.encrypt_and_digest(record)
        return ciphertext + tag


async def opened(lock: FakeLock) -> session.Session:
    sess = session.Session(lock)
    await sess.open(sat(), CAT)
    return sess


class TestConnectionRequest:
    def test_preamble_is_seven_cbor_items(self) -> None:
        assert session._CONNECTION_REQUEST_PREAMBLE == bytes(
            [0x00, 0x01, 0x00, 0x02, 0x00, 0x14, 0x02]
        )

    async def test_body_is_the_preamble_plus_a_fresh_nonce(self) -> None:
        lock = FakeLock()
        await opened(lock)
        body = lock.connection_requests[0]
        assert body.startswith(session._CONNECTION_REQUEST_PREAMBLE)
        assert len(body) == len(session._CONNECTION_REQUEST_PREAMBLE) + 12

    async def test_nonce_differs_per_session(self) -> None:
        first, second = FakeLock(), FakeLock()
        await opened(first)
        await opened(second)
        assert first.connection_requests[0] != second.connection_requests[0]


class TestParseConnectionResponse:
    def test_splits_the_flag_and_the_nonce(self) -> None:
        response = bytes([9, 9, 9, 9, 7]) + SERVER_RANDOM
        assert session.parse_connection_response(response) == (7, SERVER_RANDOM)

    @pytest.mark.parametrize("length", [0, 4, 5])
    def test_rejects_a_short_response(self, length: int) -> None:
        with pytest.raises(BleSessionError, match="too short"):
            session.parse_connection_response(bytes(length))


class TestOpen:
    async def test_authorizes_with_the_given_cat(self) -> None:
        lock = FakeLock()
        sess = await opened(lock)
        assert sess.is_open
        assert cbor2.loads(lock.plaintexts[0]) == {
            1: uweave.API_AUTHORIZATION,
            2: uweave.METHOD_AUTHORIZE,
            16: {0: 2, 1: 0, 2: CAT},
        }

    async def test_accepts_hex_tokens(self) -> None:
        # The cloud service reports both tokens as hex.
        lock = FakeLock()
        sess = session.Session(lock)
        await sess.open(sat().hex(), CAT.hex())
        assert cbor2.loads(lock.plaintexts[0])[16][2] == CAT

    async def test_extends_the_sat(self) -> None:
        lock = FakeLock()
        await opened(lock)
        extended = crypto.Macaroon.decode(cbor2.loads(lock.writes[0]))
        assert extended.caveats == [b"\x01", b"\x14"]

    async def test_mints_a_cat_when_the_lock_asks(self) -> None:
        lock = FakeLock(random_flag=3)
        asked: list[str] = []

        async def mint(value: str) -> bytes:
            asked.append(value)
            return b"minted"

        await session.Session(lock, mint).open(sat(), CAT)
        assert asked == [(bytes([3]) + SERVER_RANDOM).hex()]
        assert cbor2.loads(lock.plaintexts[0])[16][2] == b"minted"

    async def test_requires_a_minter_when_the_lock_asks(self) -> None:
        with pytest.raises(BleSessionError, match="no minter"):
            await session.Session(FakeLock(random_flag=1)).open(sat(), CAT)

    async def test_does_not_mint_when_the_lock_does_not_ask(self) -> None:
        called = False

        async def mint(value: str) -> bytes:
            nonlocal called
            called = True
            return b"minted"

        await session.Session(FakeLock(random_flag=0), mint).open(sat(), CAT)
        assert not called

    async def test_refuses_a_lock_that_cannot_prove_the_secret(self) -> None:
        sess = session.Session(FakeLock(bad_handshake=True))
        with pytest.raises(BleSessionError, match="did not verify"):
            await sess.open(sat(), CAT)
        assert not sess.is_open


class TestCall:
    async def test_requires_an_open_session(self) -> None:
        with pytest.raises(BleSessionError, match="not open"):
            await session.Session(FakeLock()).call(b"")

    async def test_method_ids_are_fixed_per_operation(self) -> None:
        # Key 2 is the method, so it does not advance from call to call.
        lock = FakeLock()
        sess = await opened(lock)
        await sess.set_locked(True, USER_ID)
        await sess.set_locked(False, USER_ID)
        assert [cbor2.loads(p)[2] for p in lock.plaintexts] == [
            uweave.METHOD_AUTHORIZE,
            uweave.METHOD_SET,
            uweave.METHOD_SET,
        ]

    async def test_set_locked(self) -> None:
        lock = FakeLock()
        sess = await opened(lock)
        await sess.set_locked(True, USER_ID)
        params = cbor2.loads(lock.plaintexts[1])[16]
        assert params[0] == uweave.TRAIT_LOCK_DATA
        assert params[1] == uweave.LOCK_STATE_WRITE
        assert params[2][0] == 1

    async def test_read_trait_unwraps_the_nested_payload(self) -> None:
        lock = FakeLock()
        sess = await opened(lock)
        lock.replies_with("BE489CEN619")
        got = await sess.read_trait(uweave.TRAIT_LOCK_DATA, uweave.MODEL_NAME)
        assert got == "BE489CEN619"
        assert cbor2.loads(lock.plaintexts[1])[2] == uweave.METHOD_GET

    async def test_read_trait_takes_another_method(self) -> None:
        lock = FakeLock()
        sess = await opened(lock)
        lock.replies_with(4)
        got = await sess.read_trait(
            uweave.TRAIT_LOCK_CONFIG,
            uweave.ACCESS_CODE_LENGTH[0],
            uweave.METHOD_ADD,
        )
        assert got == 4
        assert cbor2.loads(lock.plaintexts[1])[2] == uweave.METHOD_ADD

    async def test_a_write_reply_nests_as_deeply_as_a_read(self) -> None:
        # Both paths nest, so the unwrap lives in call() rather than in one of
        # them. A write that read one level too shallow would hand its caller
        # {17: ...} and look like an empty report.
        lock = FakeLock()
        sess = await opened(lock)
        lock.replies_with({uweave.REPORT_LOCK_STATE: 1})
        got = await sess.set_locked(True, USER_ID)
        assert got == {uweave.REPORT_LOCK_STATE: 1}

    async def test_a_reply_that_does_not_nest_is_passed_through(self) -> None:
        # Every trait reply nests its payload, so this is defensive rather
        # than a path the lock is known to take; a result with nothing nested
        # is handed back as it came rather than raising.
        lock = FakeLock()
        sess = await opened(lock)

        async def write(record: bytes) -> None:
            lock.writes.append(record)
            lock.plaintexts.append(lock._decrypt(record))
            lock._replies.append(lock._encrypt(cbor2.dumps({1: 8, 2: 7, 17: 95})))

        lock.write = write  # type: ignore[method-assign]
        assert await sess.set_locked(True, USER_ID) == 95

    async def test_read_lock_state_digs_out_the_report(self) -> None:
        # The lock-state reply does not nest under the result key, so this
        # path cannot share call()'s unwrap.
        lock = FakeLock()
        sess = await opened(lock)
        report = {uweave.REPORT_LOCK_STATE: 1, uweave.REPORT_BATTERY_LEVEL: 88}
        lock.replies_with_envelope({1: 6, 2: 3, 17: {1: {0: {0: {1: report}}}}})
        assert await sess.read_lock_state() == report
        assert cbor2.loads(lock.plaintexts[1]) == {1: 6, 2: 3}

    async def test_read_lock_state_rejects_a_trait_shaped_reply(self) -> None:
        lock = FakeLock()
        sess = await opened(lock)
        lock.replies_with({uweave.REPORT_LOCK_STATE: 1})
        with pytest.raises(UWeaveError, match="no key 1 at result"):
            await sess.read_lock_state()

    async def test_read_lock_state_surfaces_a_lock_error(self) -> None:
        lock = FakeLock()
        sess = await opened(lock)
        lock.replies_with_envelope({1: 6, 2: 3, 3: {4: 7}})
        with pytest.raises(UWeaveError) as caught:
            await sess.read_lock_state()
        assert caught.value.code == 7

    async def test_read_lock_state_requires_an_open_session(self) -> None:
        with pytest.raises(BleSessionError, match="not open"):
            await session.Session(FakeLock()).read_lock_state()

    async def test_surfaces_a_lock_error(self) -> None:
        lock = FakeLock()
        sess = await opened(lock)

        async def write(record: bytes) -> None:
            lock.writes.append(record)
            lock.plaintexts.append(lock._decrypt(record))
            lock._replies.append(lock._encrypt(cbor2.dumps({1: 8, 2: 7, 3: {4: 12}})))

        lock.write = write  # type: ignore[method-assign]
        with pytest.raises(UWeaveError) as caught:
            await sess.set_locked(True, USER_ID)
        assert caught.value.code == 12

    async def test_counters_advance_across_calls(self) -> None:
        # Three calls, three distinct nonces in each direction. A repeat would
        # mean a reused nonce, which EAX does not survive.
        lock = FakeLock()
        sess = await opened(lock)
        await sess.set_locked(True, USER_ID)
        await sess.set_locked(True, USER_ID)
        assert len(set(lock.writes[1:])) == 3
