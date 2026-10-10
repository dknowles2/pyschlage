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

   The lock-state read is the least certain piece. Its reply hides the report
   four levels below the envelope's result, through a mixture of maps and
   arrays that only a real lock will settle, so
   :func:`pyschlage.ble.uweave.lock_state_report` indexes whichever each level
   turns out to be and raises when a level is neither.
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
