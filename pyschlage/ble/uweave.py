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

Its reply is the one that does not put its payload at ``[17][17]``. The report
is still inside :data:`RESULT`, four map levels further in, so
:meth:`pyschlage.ble.session.Session.call` is no use to it and
:func:`lock_state_report` walks to it instead.
"""

API_TRAIT = 8
"""API that reads and writes a trait's attributes."""

METHOD_AUTHORIZE = 1
"""Method that authorizes a session."""

# Methods 2, 3 and 5 mean different things on different traits, and have no
# names here for that reason. They were once called METHOD_ADD, METHOD_UPDATE
# and METHOD_LIST, from the call sites outside TRAIT_ACCESS_CODE, and on that
# trait all three names are wrong in the worst direction: 2 deletes a code, 3
# adds or overwrites one, and 5 deletes every code on the lock. A name that is
# true of one trait and dangerous on another is worse than a number, because it
# travels with the constant while any warning stays where it was written.

METHOD_2 = 2
"""Method id 2, whose meaning depends on the trait it is sent to.

On :data:`TRAIT_LOCK_CONFIG` it reads a scalar. On :data:`TRAIT_ACCESS_CODE`
it deletes one access code, keyed by the code's value. Do not reach for it on
a trait where it has not been observed.
"""

METHOD_3 = 3
"""Method id 3, whose meaning depends on the trait it is sent to.

On :data:`TRAIT_ACCESS_CODE` it adds a code, overwrites a code or selects one
for reading, depending only on the attribute. Under :data:`API_LOCK_STATE` the
same id reads the lock state, which is :data:`METHOD_READ_LOCK_STATE`.
"""

METHOD_GET = 4
"""Method that reads a trait's attribute on every trait but one.

Not on :data:`TRAIT_ACCESS_CODE`. This id with attribute 0 correlates with an
access code being added, on two locks, so there it writes. Reading a trait is
what this does everywhere it has been sent deliberately, which is not the same
as what it does everywhere.
"""

METHOD_5 = 5
"""Method id 5, whose meaning depends on the trait it is sent to.

On :data:`TRAIT_ACCESS_CODE` with attribute 2 it deletes every access code on
the lock, with no confirmation and no undo.
"""

METHOD_SET = 7
"""Method that writes a trait's attribute.

The other id that appears to mean the same thing on every trait observed.
"""

METHOD_READ_LOCK_STATE = 3
"""Method that reads the lock state, under :data:`API_LOCK_STATE`.

Method ids are scoped to their API, so this is not :data:`METHOD_3`
despite sharing its number.
"""

TRAIT_LOCK_DATA = 1
"""Trait holding a lock's identity, firmware, time and bolt state."""

TRAIT_ACCESS_CODE = 4
"""Trait holding a lock's access codes and credentials.

Nothing here builds a call against it, and nothing should without a reason
better than curiosity.

.. danger::

   Reading this trait is not safe to work out by trying ids. An attempt to do
   so, sending methods and attributes that returned reply-shaped answers,
   added an access code to two locks and deleted every code on one of them.
   The lock's event log is the only reason that was noticed: the replies looked
   like reads throughout.

   ``METHOD_GET`` is not a read here, whatever it is elsewhere -- that method
   with attribute 0 is what both added codes correlate with. These are the
   shapes to recognise and not send, from the Android app:

   .. code-block:: text

      delete every code  {1: 8, 2: 5, 16: {0: 4, 1: 2}}
      delete one code    {1: 8, 2: 2, 16: {0: 4, 1: 1, 2: {2: <code>}}}
      add a code         {1: 8, 2: 3, 16: {0: 4, 1: 0, 2: {...}}}
      overwrite a code   {1: 8, 2: 3, 16: {0: 4, 1: 4, 2: {...}}}

   Deleting one code is keyed by the code's value rather than its UUID, so a
   stale value deletes whatever now holds it.

Access codes are the cloud service's business in this library, on every
transport. :class:`pyschlage.aio.LockBackend` carries only the operations every
backend can perform, and this is not one of them.
"""

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
# A BE489WB answers -16 here. That is -4 hours if the unit is quarter hours,
# which would fit the lock's location, but the unit is not established and
# nothing in the app interprets the value.
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

# Real locks send keys nothing above accounts for, and nothing in the app
# looks any of them up, so what writes them cannot be learned from it either.
# They are left alone rather than guessed at.
#
#   BE489WB  {13: 0, 15: 0, 16: 0, 18: 1, 19: 17, 20: '15.00.01367012'}
#   BE499WB2 {13: 0, 15: 3, 16: 0, 18: 1, 19: 2, 20: '05.00.01300215', 22: 2}
#
# Key 19 counts something that advances per session. The BE489WB reported 17
# and then 18 across two connections minutes apart, with nothing else about
# the lock changed; the BE499WB2, connected to far less, reported 2 both
# times. So it is a counter rather than a constant, which rules out reading it
# as a state or a mode. What it counts is unknown.
#
# Key 20 is probably the main firmware version: it equals what trait 1
# attribute 5 returns on both locks, and the app fetches the string that way
# while ignoring the copy in the report. Probably is not enough to map it.
#
# Keys 15 and 19 differ between the two models and 22 appears on only one,
# while each held the same value across repeated reads of the same lock. So
# they describe the lock rather than report its state -- a capability or a
# configuration -- which is as far as two locks narrow it.
#
# Neither lock reports key 25 at all, which is why every key here is checked
# rather than assumed -- including on a model expected to have a door sensor.

# Where a lock-state reply hides its report, relative to the envelope's
# result. Every other reply this library reads nests once more, under RESULT
# again; this one goes four map levels deeper instead.
_LOCK_STATE_REPORT_PATH = (1, 0, 0, 1)

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


def read_lock_state() -> bytes:
    """Encodes the call that reads a lock's current state.

    The record carries no params at all.

    :rtype: bytes
    """
    return encode_request(API_LOCK_STATE, METHOD_READ_LOCK_STATE)


def _path_to(depth: int) -> str:
    """Names the position a walk down the lock-state path has reached."""
    return "result" + "".join(f"[{k}]" for k in _LOCK_STATE_REPORT_PATH[:depth])


def lock_state_report(result: Any) -> Any:
    """Digs the report out of a lock-state reply.

    Every level is a map keyed by an unsigned integer, none of them arrays:
    the app's chain is five ``Map.get(UnsignedInteger)`` calls, and in the CBOR
    library it bundles ``get`` exists only on maps, so an array level could not
    have compiled.

    :param result: The envelope's result, as :func:`decode_response` returns
        it.
    :rtype: Any
    :raise pyschlage.exceptions.UWeaveError: When the reply is not shaped like
        a lock-state reply.
    """
    value = result
    for depth, key in enumerate(_LOCK_STATE_REPORT_PATH):
        if not isinstance(value, dict):
            raise UWeaveError(
                f"lock state reply holds {type(value).__name__} at "
                f"{_path_to(depth)}, expected a map"
            )
        if key not in value:
            raise UWeaveError(f"lock state reply has no key {key} at {_path_to(depth)}")
        value = value[key]
    return value


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
        lock config group's scalar reads use :data:`METHOD_2` instead.
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
