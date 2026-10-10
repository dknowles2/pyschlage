"""Bluetooth LE support for Schlage locks.

The locks speak Google's uWeave: CBOR-encoded RPC records over two GATT
characteristics, inside an AES-EAX session authorized by macaroons the cloud
service issues. ``PROTOCOL.md`` documents what is known of it.

This package needs the ``ble`` extra::

    pip install pyschlage[ble]

This has been exercised against a BE489WB, end to end: the handshake, an
authorized session, trait and settings reads, the lock-state read, and
locking and unlocking the bolt. No other model has been tried.

``scripts/ble_probe.py`` in the repository walks the whole protocol a stage at
a time against a real lock, and is read-only unless asked otherwise.

.. note::

   Two things to know when reaching for this.

A lock is matched by the MAC in its manufacturer data, not by its advertised
   name. The locks put it seven bytes into their Allegion payload, and it is
   the only identifier that survives macOS, where Core Bluetooth reports its
   own handles. Two locks both advertise as ``SCHLAGE...``, and a lock that is
   not the one whose SAT you hold answers the handshake's first step and then
   goes silent, which is indistinguishable from a protocol bug.
   :func:`discover` cannot do this matching, since it filters on a service
   UUID the locks do not advertise; ``scripts/ble_probe.py`` shows what does
   work.

   A record the lock sends that fails to decrypt, or that arrives
   unexpectedly, advances the receive counter and desynchronises the session
   for good. The app behaves the same way, so this may be inherent; recovery
   is a new session.
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
