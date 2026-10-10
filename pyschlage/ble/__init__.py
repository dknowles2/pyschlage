"""Bluetooth LE support for Schlage locks.

The locks speak Google's uWeave: CBOR-encoded RPC records over two GATT
characteristics, inside an AES-EAX session authorized by macaroons the cloud
service issues. ``PROTOCOL.md`` documents what is known of it.

This package needs the ``ble`` extra::

    pip install pyschlage[ble]

.. warning::

   None of this has been exercised against a real lock. It reproduces what
   reading the Android app revealed, so treat it as a starting point for
   someone with a lock in reach rather than as a proven transport.

   One known rough edge: a record the lock sends that fails to decrypt, or
   that arrives unexpectedly, advances the receive counter and desynchronises
   the session for good. The app behaves the same way, so this may be
   inherent; recovery is a new session.

   The lock-state read is the least certain piece, though only in one
   respect: its reply path is four map levels below the envelope's result, and
   while the levels are known to be maps, whether the path itself is right is
   the part no amount of reading settles.

   The two likely first failures are easy to tell apart, which is worth
   knowing before reaching for a sniffer. A handshake that is wrong never
   produces a session at all, so nothing decrypts and
   :meth:`pyschlage.ble.Session.open` raises. A reply path that is wrong
   arrives instead as a :class:`pyschlage.exceptions.UWeaveError` naming the
   level that did not fit. So a lock that locks and unlocks but fails
   :meth:`pyschlage.ble.BleBackend.get_state` localises the problem to the
   lock-state path by itself.
"""

from .backend import BleBackend, GattChannel, connect, discover
from .session import Session

__all__ = (
    "BleBackend",
    "GattChannel",
    "Session",
    "connect",
    "discover",
)
