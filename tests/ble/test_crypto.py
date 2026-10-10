"""Tests for the uWeave session cryptography.

Where a construction can be expressed another way, these tests recompute it
with the standard library rather than asserting what the implementation
happens to produce. That checks the code against the documented construction;
it cannot check the documented construction against a real lock.
"""

import hashlib
import hmac
import io

import cbor2
from Crypto.Cipher import AES
import pytest

from pyschlage.ble import crypto
from pyschlage.exceptions import BleSessionError

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


class TestDecodeToken:
    def test_decodes_hex(self) -> None:
        assert crypto.decode_token("cafe01") == b"\xca\xfe\x01"

    def test_passes_bytes_through(self) -> None:
        assert crypto.decode_token(b"\xca\xfe") == b"\xca\xfe"

    def test_rejects_what_is_not_hex(self) -> None:
        with pytest.raises(ValueError):
            crypto.decode_token("not hex")


class TestMacaroon:
    def test_round_trip(self) -> None:
        macaroon = crypto.Macaroon(caveats=[b"\x01", b"\x02"], tag=SAT_TAG)
        assert crypto.Macaroon.decode(macaroon.encode()) == macaroon

    def test_decodes_an_outer_byte_string(self) -> None:
        macaroon = crypto.Macaroon(caveats=[b"\x01"], tag=SAT_TAG)
        wrapped = cbor2.dumps(macaroon.encode())
        assert crypto.Macaroon.decode(wrapped) == macaroon

    def test_encodes_two_top_level_items(self) -> None:
        # The caveats and the tag follow one another; an array holding both
        # would not decode on the lock.
        macaroon = crypto.Macaroon(caveats=[b"\x14"], tag=SAT_TAG)
        encoded = macaroon.encode()
        assert encoded == cbor2.dumps([b"\x14"]) + cbor2.dumps(SAT_TAG)

        decoder = cbor2.CBORDecoder(io.BytesIO(encoded))
        assert decoder.decode() == [b"\x14"]
        assert decoder.decode() == SAT_TAG

    def test_matches_the_shape_of_a_real_sat(self) -> None:
        # A live SAT is one outer byte string whose first inner byte is 0x82,
        # the header of a two-element array, with the tag following it.
        macaroon = crypto.Macaroon(caveats=[b"\x01", b"\x02"], tag=SAT_TAG)
        sat = cbor2.dumps(macaroon.encode())
        inner = cbor2.loads(sat)
        assert isinstance(inner, bytes)
        assert inner[0] == 0x82
        assert crypto.Macaroon.decode(sat) == macaroon

    def test_a_33_byte_macaroon_wraps_as_a_two_byte_header(self) -> None:
        # The observed SAT is 35 bytes on the wire: 0x58 0x21 then 33 bytes.
        sat = cbor2.dumps(bytes(33))
        assert sat[:2] == bytes([0x58, 0x21])
        assert len(sat) == 35

    def test_rejects_caveats_that_are_not_an_array(self) -> None:
        with pytest.raises(BleSessionError, match="expected caveats"):
            crypto.Macaroon.decode(cbor2.dumps(42))

    def test_rejects_a_tag_that_is_not_bytes(self) -> None:
        bad = cbor2.dumps([b"\x01"]) + cbor2.dumps("not bytes")
        with pytest.raises(BleSessionError, match="expected bytes"):
            crypto.Macaroon.decode(bad)


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
        return cbor2.dumps(macaroon.encode())

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

    def test_accepts_a_hex_sat(self) -> None:
        record, tag = crypto.extend_sat(self.sat(), CLIENT_RANDOM, SERVER_RANDOM)
        assert tag == SAT_TAG
        assert record


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

    def test_has_no_way_to_restart_the_counters(self) -> None:
        # Restarting them under a live key would repeat EAX nonces.
        assert not hasattr(self.cipher(), "reset")

    def test_counter_overflow_is_refused(self) -> None:
        cipher = self.cipher()
        cipher._counters[crypto.APP_TO_LOCK] = 0x100
        with pytest.raises(ValueError, match="overflowed"):
            cipher.encrypt(b"a")
