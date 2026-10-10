"""Tests for the uWeave RPC envelope."""

from uuid import UUID

import cbor2
import pytest

from pyschlage.ble import uweave
from pyschlage.device import LockState
from pyschlage.exceptions import UWeaveError

USER_ID = "8b1a9953-c461-1296-a827-abf8c47804d7"


class TestUserIdBytes:
    def test_is_sixteen_big_endian_bytes(self) -> None:
        got = uweave.user_id_bytes(USER_ID)
        assert len(got) == 16
        assert got == UUID(USER_ID).bytes
        assert got[:4] == bytes([0x8B, 0x1A, 0x99, 0x53])

    def test_rejects_a_non_uuid(self) -> None:
        with pytest.raises(ValueError):
            uweave.user_id_bytes("not-a-uuid")


class TestEncodeRequest:
    def test_without_params(self) -> None:
        record = uweave.encode_request(uweave.API_LOCK_STATE, 3)
        assert cbor2.loads(record) == {1: 6, 2: 3}

    def test_with_params(self) -> None:
        record = uweave.encode_request(uweave.API_TRAIT, 4, {0: 1})
        assert cbor2.loads(record) == {1: 8, 2: 4, 16: {0: 1}}


class TestDecodeResponse:
    def test_returns_the_result(self) -> None:
        record = cbor2.dumps({1: 6, 2: 1, 17: {0: 1, 21: 95}})
        assert uweave.decode_response(record) == {0: 1, 21: 95}

    def test_leaves_a_trait_payload_nested(self) -> None:
        # A trait read nests its payload under a second result key; unwrapping
        # it is the caller's business, since a lock-state report does not.
        record = cbor2.dumps({1: 8, 2: 1, 17: {17: "BE489CEN619"}})
        assert uweave.decode_response(record) == {17: "BE489CEN619"}

    def test_missing_result_is_none(self) -> None:
        assert uweave.decode_response(cbor2.dumps({1: 5, 2: 1})) is None

    def test_raises_on_an_error_map(self) -> None:
        record = cbor2.dumps({1: 8, 2: 1, 3: {4: 42}})
        with pytest.raises(UWeaveError, match="error 42") as caught:
            uweave.decode_response(record)
        assert caught.value.code == 42

    def test_raises_without_an_error_code(self) -> None:
        record = cbor2.dumps({1: 8, 2: 1, 3: {}})
        with pytest.raises(UWeaveError) as caught:
            uweave.decode_response(record)
        assert caught.value.code is None

    def test_raises_when_the_error_is_not_a_map(self) -> None:
        record = cbor2.dumps({1: 8, 2: 1, 3: "broken"})
        with pytest.raises(UWeaveError) as caught:
            uweave.decode_response(record)
        assert caught.value.code is None

    def test_raises_when_the_response_is_not_a_map(self) -> None:
        with pytest.raises(UWeaveError, match="not a map"):
            uweave.decode_response(cbor2.dumps([1, 2, 3]))


class TestAuthorizeCat:
    def test_matches_the_documented_record(self) -> None:
        record = uweave.authorize_cat(b"\xca\xfe")
        assert cbor2.loads(record) == {1: 5, 2: 1, 16: {0: 2, 1: 0, 2: b"\xca\xfe"}}

    def test_request_id_is_overridable(self) -> None:
        record = uweave.authorize_cat(b"\xca\xfe", request_id=9)
        assert cbor2.loads(record)[2] == 9


class TestTraits:
    def test_read(self) -> None:
        record = uweave.read_trait(uweave.TRAIT_LOCK_DATA, uweave.SERIAL_NUMBER, 2)
        assert cbor2.loads(record) == {1: 8, 2: 2, 16: {0: 1, 1: 4}}

    def test_write(self) -> None:
        record = uweave.write_trait(
            uweave.TRAIT_LOCK_CONFIG, uweave.BEEPER_ENABLED[1], 1, USER_ID, 5
        )
        assert cbor2.loads(record) == {
            1: 8,
            2: 5,
            16: {0: 5, 1: 2, 2: {0: 1, 1: UUID(USER_ID).bytes}},
        }

    def test_config_setters_are_one_below_their_getter(self) -> None:
        for read, write in (
            uweave.BEEPER_ENABLED,
            uweave.AUTO_LOCK_TIME,
            uweave.ALARM_SELECTION,
            uweave.ALARM_SENSITIVITY,
            uweave.LOCK_AND_LEAVE_ENABLED,
            uweave.TIMEZONE,
        ):
            assert read is not None and write is not None
            assert write == read - 1


class TestSetLocked:
    def test_lock(self) -> None:
        record = uweave.set_locked(True, USER_ID, 1)
        params = cbor2.loads(record)[16]
        assert params[0] == uweave.TRAIT_LOCK_DATA
        assert params[1] == uweave.LOCK_STATE_WRITE
        assert params[2][0] == LockState.LOCKED

    def test_unlock(self) -> None:
        record = uweave.set_locked(False, USER_ID, 1)
        assert cbor2.loads(record)[16][2][0] == LockState.UNLOCKED

    def test_value_is_a_plain_int(self) -> None:
        # cbor2 would encode an IntEnum as its int anyway, but keeping the
        # ordinal plain means the record cannot depend on that.
        value = cbor2.loads(uweave.set_locked(True, USER_ID, 1))[16][2][0]
        assert type(value) is int
