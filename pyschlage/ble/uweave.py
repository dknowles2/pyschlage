"""The uWeave RPC envelope.

A record is a CBOR map with small integer keys: the API being called, the
method within it, and either params or a result. A failure carries an error
map instead of a result.

Only the calls ``PROTOCOL.md`` documents precisely are built here. Where it
records a call's existence but not its params -- the lock-state read, most of
the commissioning and firmware operations -- there is no builder, since one
would be a guess.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import cbor2

from ..device import LockState
from ..exceptions import UWeaveError

API_ID = 1
"""Envelope key holding the id of the API being called."""

METHOD_ID = 2
"""Envelope key holding the method being called within the API.

This is a fixed constant per operation, not a counter: the app hardcodes it at
each call site and nothing echoes or matches it.
"""

ERROR = 3
"""Envelope key holding the error map, present only on a failure."""

ERROR_CODE = 4
"""Key of the error code, inside the error map."""

PARAMS = 16
"""Envelope key holding the call's params."""

RESULT = 17
"""Envelope key holding the call's result.

Note that this collides with :data:`REPORT_OPERATING_MODE`, which is also
``17``. Unwrapping "key 17 if it is there" is therefore ambiguous in general;
see :meth:`pyschlage.ble.session.Session.call` for why it is safe for the
replies this library reads.
"""

API_AUTHORIZATION = 5
"""API that authorizes a session with a CAT."""

API_LOCK_STATE = 6
"""API that reads a lock's current state.

There is no builder for it. The record is just ``{1: 6, 2: 3}`` with no
params, but its reply buries the report at ``envelope[17][1][0][0][1]``
rather than the ``envelope[17][17]`` every API 8 reply uses, so it cannot go
through :meth:`pyschlage.ble.session.Session.call`. Nothing needs it yet: a
lock-state report comes back on the reply to a lock or unlock.
"""

API_TRAIT = 8
"""API that reads and writes a trait's attributes."""

METHOD_AUTHORIZE = 1
"""Method that authorizes a session."""

METHOD_ADD = 2
"""Method that adds a record, or reads a lock config group's scalar."""

METHOD_UPDATE = 3
"""Method that updates an existing record."""

METHOD_GET = 4
"""Method that reads a trait's attribute."""

METHOD_LIST = 5
"""Method that lists a trait's records."""

METHOD_SET = 7
"""Method that writes a trait's attribute."""

TRAIT_LOCK_DATA = 1
"""Trait holding a lock's identity, firmware, time and bolt state."""

TRAIT_ACCESS_CODE = 4
"""Trait holding a lock's access codes and credentials."""

TRAIT_LOCK_CONFIG = 5
"""Trait holding a lock's configurable settings."""

TRAIT_ACCESS_POINT = 6
"""Trait holding the WiFi access point parameters."""

# Attributes of TRAIT_LOCK_DATA. Each is readable or writable, not both.
LOCK_STATE_WRITE = 0
MANUFACTURER_NAME = 2
MODEL_NAME = 3
SERIAL_NUMBER = 4
FIRMWARE_VERSION = 5
CURRENT_TIME_WRITE = 6
CURRENT_TIME = 7
BATTERY_LEVEL = 12
EXTENDED_FIRMWARE_VERSIONS = 15

# Attributes of TRAIT_LOCK_CONFIG, as (read, write) pairs. The writable
# attribute is consistently the readable one minus one.
BEEPER_ENABLED = (3, 2)
AUTO_LOCK_TIME = (5, 4)
ALARM_SELECTION = (9, 8)
ALARM_SENSITIVITY = (11, 10)
LOCK_AND_LEAVE_ENABLED = (13, 12)
ACCESS_CODE_LENGTH = (15, None)
TIMEZONE = (21, 20)
MAX_USER_CODES = (None, 28)
# Operating mode does not follow the getter-minus-one rule: the write id
# depends on what is being asked for. 23 sets the mode normally, 26 enables
# simultaneous mode, and 27 is the id a Sense Pro takes.
OPERATING_MODE = (27, 23)
OPERATING_MODE_SIMULTANEOUS_WRITE = 26
OPERATING_MODE_SENSE_PRO_WRITE = 27

# Keys of a lock-state report. The report comes back directly under RESULT,
# unlike a trait read, which nests its payload one level deeper.
REPORT_LOCK_STATE = 0
REPORT_BATTERY_STATE = 12
REPORT_ALARM_SELECTION = 14
REPORT_OPERATING_MODE = 17  # Same number as RESULT; see its docstring.
REPORT_BATTERY_LEVEL = 21
REPORT_DOOR_STATE = 25
REPORT_DUAL_DOOR_PAIRING = 128
REPORT_DUAL_DOOR_MAC = 129
REPORT_DUAL_DOOR_CONFIG = 130

# Params of an authorization call.
_AUTH_KIND = 0
_AUTH_ROLE = 1
_AUTH_TOKEN = 2
_AUTH_KIND_CAT = 2
_AUTH_ROLE_DEFAULT = 0

# Params of a trait call.
_PARAM_TRAIT = 0
_PARAM_ATTRIBUTE = 1
_PARAM_WRITE = 2
_WRITE_VALUE = 0
_WRITE_USER_ID = 1


def user_id_bytes(user_id: str) -> bytes:
    """Returns an account id as the 16 big-endian bytes a write carries.

    :param user_id: The account's UUID, as the cloud service reports it.
    :type user_id: str
    :rtype: bytes
    :raise ValueError: When the id is not a UUID.
    """
    return UUID(user_id).bytes


def encode_request(api_id: int, method_id: int, params: Any = None) -> bytes:
    """Encodes a request record.

    :param api_id: The API to call.
    :type api_id: int
    :param method_id: The method within that API.
    :type method_id: int
    :param params: The call's params, omitted when None.
    :rtype: bytes
    """
    record: dict[int, Any] = {API_ID: api_id, METHOD_ID: method_id}
    if params is not None:
        record[PARAMS] = params
    return cbor2.dumps(record)


def decode_response(record: bytes) -> Any:
    """Decodes a response record and returns its result.

    A trait read nests its payload one level deeper, under another
    :data:`RESULT` key; a lock-state report is the result itself. The caller
    knows which it asked for.

    :param record: The decoded, decrypted CBOR record.
    :type record: bytes
    :raise pyschlage.exceptions.UWeaveError: When the lock reports a failure.
    """
    response = cbor2.loads(record)
    if not isinstance(response, dict):
        raise UWeaveError(f"response is not a map: {type(response).__name__}")
    if ERROR in response:
        error = response[ERROR]
        code = error.get(ERROR_CODE) if isinstance(error, dict) else None
        raise UWeaveError(f"lock reported error {code}", code=code)
    return response.get(RESULT)


def authorize_cat(cat: bytes) -> bytes:
    """Encodes the call that authorizes a session with a CAT.

    This is the first encrypted record of a session.

    :param cat: The Cloud Access Token, decoded to bytes.
    :type cat: bytes
    :rtype: bytes
    """
    return encode_request(
        API_AUTHORIZATION,
        METHOD_AUTHORIZE,
        {
            _AUTH_KIND: _AUTH_KIND_CAT,
            _AUTH_ROLE: _AUTH_ROLE_DEFAULT,
            _AUTH_TOKEN: cat,
        },
    )


def read_trait(trait: int, attribute: int, method_id: int = METHOD_GET) -> bytes:
    """Encodes a read of one attribute of a trait.

    :param trait: The trait to read, e.g. :data:`TRAIT_LOCK_DATA`.
    :type trait: int
    :param attribute: The attribute of that trait.
    :type attribute: int
    :param method_id: The method to call. The default suits a trait read; the
        lock config group's scalar reads use :data:`METHOD_ADD` instead.
    :type method_id: int
    :rtype: bytes
    """
    return encode_request(
        API_TRAIT, method_id, {_PARAM_TRAIT: trait, _PARAM_ATTRIBUTE: attribute}
    )


def write_trait(
    trait: int, attribute: int, value: Any, user_id: str, method_id: int = METHOD_SET
) -> bytes:
    """Encodes a write of one attribute of a trait.

    :param trait: The trait to write, e.g. :data:`TRAIT_LOCK_DATA`.
    :type trait: int
    :param attribute: The attribute of that trait.
    :type attribute: int
    :param value: The value to write.
    :param user_id: The account making the change, which the lock records.
    :type user_id: str
    :param method_id: The method to call.
    :type method_id: int
    :rtype: bytes
    :raise ValueError: When the user id is not a UUID.
    """
    return encode_request(
        API_TRAIT,
        method_id,
        {
            _PARAM_TRAIT: trait,
            _PARAM_ATTRIBUTE: attribute,
            _PARAM_WRITE: {
                _WRITE_VALUE: value,
                _WRITE_USER_ID: user_id_bytes(user_id),
            },
        },
    )


def set_locked(locked: bool, user_id: str) -> bytes:
    """Encodes the call that locks or unlocks the lock.

    :param locked: True to lock, False to unlock.
    :type locked: bool
    :param user_id: The account making the change, which the lock records.
    :type user_id: str
    :rtype: bytes
    :raise ValueError: When the user id is not a UUID.
    """
    # The app sends its enum's ordinal, which happens to equal the numeric
    # value for every state that is ever written: it declares UNLOCKED(0)
    # through DEADLOCKED(6) in order, and only INVALID(-1) sits out of place.
    # So sending the value, as int() does, is simply correct. Deriving the
    # number from a reimplementation's own declaration order would not be.
    state = LockState.LOCKED if locked else LockState.UNLOCKED
    return write_trait(TRAIT_LOCK_DATA, LOCK_STATE_WRITE, int(state), user_id)
