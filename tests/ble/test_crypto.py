"""Tests for the uWeave session cryptography.

Where a construction can be expressed another way, these tests recompute it
with the standard library rather than asserting what the implementation
happens to produce. That checks the code against the documented construction;
it cannot check the documented construction against a real lock.
"""

import hashlib
import hmac

import cbor2
from Crypto.Cipher import AES
import pytest

from pyschlage.ble import crypto

CLIENT_RANDOM = bytes(range(crypto.RANDOM_LEN))
SERVER_RANDOM = bytes(range(100, 100 + crypto.RANDOM_LEN))
SAT_TAG = bytes(range(32, 32 + crypto.TAG_LEN))


def hkdf_sha256(ikm: bytes, salt: bytes, info: bytes, length: int) -> bytes:
    """A plain HKDF-SHA256, to check the one in the module under test."""
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    okm = b""
    block = b""
    counter = 1
    while len(okm) < length:
        block = hmac.new(prk, block + info + bytes([counter]), hashlib.sha256).digest()
        okm += block
        counter += 1
    return okm[:length]


class TestMacaroon:
    def test_round_trip(self) -> None:
        macaroon = crypto.Macaroon(caveats=[b"\x01", b"\x02"], tag=SAT_TAG)
        assert crypto.Macaroon.decode(macaroon.encode()) == macaroon

    def test_decodes_an_outer_byte_string(self) -> None:
        macaroon = crypto.Macaroon(caveats=[b"\x01"], tag=SAT_TAG)
        wrapped = cbor2.dumps(macaroon.encode())
        assert crypto.Macaroon.decode(wrapped) == macaroon

    def test_encodes_as_a_pair(self) -> None:
        macaroon = crypto.Macaroon(caveats=[b"\x14"], tag=SAT_TAG)
        assert cbor2.loads(macaroon.encode()) == [[b"\x14"], SAT_TAG]


class TestSessionTag:
    def test_matches_the_documented_construction(self) -> None:
        inner = cbor2.dumps(bytes([1]) + CLIENT_RANDOM + SERVER_RANDOM)
        outer = cbor2.dumps(bytes([0x14]) + inner)
        want = hmac.new(SAT_TAG, outer, hashlib.sha256).digest()[:16]
        got = crypto.session_tag(SAT_TAG, 1, CLIENT_RANDOM, SERVER_RANDOM)
        assert got == want

    def test_is_truncated(self) -> None:
        tag = crypto.session_tag(SAT_TAG, 1, CLIENT_RANDOM, SERVER_RANDOM)
        assert len(tag) == crypto.TAG_LEN

    def test_index_changes_the_tag(self) -> None:
        first = crypto.session_tag(SAT_TAG, 1, CLIENT_RANDOM, SERVER_RANDOM)
        second = crypto.session_tag(SAT_TAG, 2, CLIENT_RANDOM, SERVER_RANDOM)
        assert first != second

    def test_randoms_change_the_tag(self) -> None:
        tag = crypto.session_tag(SAT_TAG, 1, CLIENT_RANDOM, SERVER_RANDOM)
        other = crypto.session_tag(SAT_TAG, 1, CLIENT_RANDOM, bytes(len(SERVER_RANDOM)))
        assert tag != other


class TestExtendSat:
    def sat(self) -> bytes:
        macaroon = crypto.Macaroon(caveats=[b"\x01"], tag=SAT_TAG)
        return cbor2.dumps([macaroon.encode()])

    def test_appends_the_session_caveat_and_retags(self) -> None:
        record, sat_tag = crypto.extend_sat(self.sat(), CLIENT_RANDOM, SERVER_RANDOM)
        assert sat_tag == SAT_TAG

        extended = crypto.Macaroon.decode(cbor2.loads(record))
        assert extended.caveats == [b"\x01", b"\x14"]
        assert extended.tag == crypto.session_tag(
            SAT_TAG, 1, CLIENT_RANDOM, SERVER_RANDOM
        )

    def test_record_is_the_macaroon_wrapped_in_cbor(self) -> None:
        record, _ = crypto.extend_sat(self.sat(), CLIENT_RANDOM, SERVER_RANDOM)
        assert isinstance(cbor2.loads(record), bytes)


class TestDeriveSession:
    def test_matches_the_documented_construction(self) -> None:
        ikm = bytes([2]) + CLIENT_RANDOM + SERVER_RANDOM + SAT_TAG
        want = hkdf_sha256(ikm, salt=crypto._HKDF_SALT, info=b"session key", length=32)
        key, session_id = crypto.derive_session(CLIENT_RANDOM, SERVER_RANDOM, SAT_TAG)
        assert key == want[:16]
        assert session_id == want[16:]

    def test_lengths(self) -> None:
        key, session_id = crypto.derive_session(CLIENT_RANDOM, SERVER_RANDOM, SAT_TAG)
        assert len(key) == crypto.SESSION_KEY_LEN
        assert len(session_id) == 16

    def test_salt_is_32_bytes(self) -> None:
        assert len(crypto._HKDF_SALT) == 32


class TestRecordNonce:
    def test_layout(self) -> None:
        session_id = bytes(range(16))
        nonce = crypto.record_nonce(session_id, crypto.APP_TO_LOCK, 7)
        assert nonce == session_id + bytes([0x01, 0x00, 0x00, 0x07])
        assert len(nonce) == 20


class TestRecordCipher:
    def cipher(self) -> crypto.RecordCipher:
        key, session_id = crypto.derive_session(CLIENT_RANDOM, SERVER_RANDOM, SAT_TAG)
        return crypto.RecordCipher(key, session_id)

    def test_round_trip(self) -> None:
        # One cipher encrypts and another decrypts, since the two directions
        # have separate counters and a real session has one cipher per end.
        record = cbor2.dumps({1: 5, 2: 1})
        sealed = self.cipher().encrypt(record)
        assert sealed != record
        assert len(sealed) == len(record) + crypto.MAC_LEN

        other = self.cipher()
        nonce = crypto.record_nonce(other._session_id, crypto.APP_TO_LOCK, 1)
        opened = AES.new(
            other._key, AES.MODE_EAX, nonce=nonce, mac_len=crypto.MAC_LEN
        ).decrypt_and_verify(sealed[: -crypto.MAC_LEN], sealed[-crypto.MAC_LEN :])
        assert opened == record

    def test_counters_start_at_one_and_advance(self) -> None:
        cipher = self.cipher()
        assert cipher._counters == {crypto.APP_TO_LOCK: 1, crypto.LOCK_TO_APP: 1}
        first = cipher.encrypt(b"a")
        second = cipher.encrypt(b"a")
        # Same plaintext, different nonce, so different ciphertext.
        assert first != second

    def test_directions_have_separate_counters(self) -> None:
        cipher = self.cipher()
        cipher.encrypt(b"a")
        assert cipher._counters[crypto.APP_TO_LOCK] == 2
        assert cipher._counters[crypto.LOCK_TO_APP] == 1

    def test_decrypt_verifies_the_tag(self) -> None:
        sealed = bytearray(self.cipher().encrypt(b"payload"))
        sealed[-1] ^= 0xFF
        with pytest.raises(ValueError):
            self.cipher().decrypt(bytes(sealed))

    def test_decrypt_rejects_a_short_record(self) -> None:
        with pytest.raises(ValueError, match="shorter than"):
            self.cipher().decrypt(bytes(crypto.MAC_LEN - 1))

    def test_reset_restarts_the_counters(self) -> None:
        cipher = self.cipher()
        first = cipher.encrypt(b"a")
        cipher.encrypt(b"a")
        cipher.reset()
        assert cipher.encrypt(b"a") == first

    def test_counter_overflow_is_refused(self) -> None:
        cipher = self.cipher()
        cipher._counters[crypto.APP_TO_LOCK] = 0x100
        with pytest.raises(ValueError, match="overflowed"):
            cipher.encrypt(b"a")
