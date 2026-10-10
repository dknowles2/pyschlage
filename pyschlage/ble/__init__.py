"""Bluetooth LE support for Schlage locks.

The locks speak Google's uWeave: CBOR-encoded RPC records over two GATT
characteristics, inside an AES-EAX session authorized by macaroons the cloud
service issues. ``PROTOCOL.md`` documents what is known of it.

This package needs the ``ble`` extra::

    pip install pyschlage[ble]

.. warning::

   None of this has been exercised against a real lock. It reproduces what
   reading the Android app revealed, and two details are still guesses: the
   encoding of the ``SAT`` and ``CAT`` strings, which the session takes as
   bytes rather than decoding itself, and whether the connection request
   carries a leading byte of its own. Treat it as a starting point for someone
   with a lock in reach, not as a working transport.
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
