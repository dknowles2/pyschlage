"""Bluetooth LE support for Schlage locks.

The locks speak Google's uWeave: CBOR-encoded RPC records over two GATT
characteristics, inside an AES-EAX session authorized by macaroons the cloud
service issues. ``PROTOCOL.md`` documents what is known of it.

This package needs the ``ble`` extra::

    pip install pyschlage[ble]

The read path has been exercised against a BE489WB: the handshake, an
authorized session, trait and settings reads, and the lock-state read all
work against that lock. Writing -- locking, unlocking, changing a setting --
has not been tried on hardware yet, and the BE499 has not been tried at all.

``scripts/ble_probe.py`` in the repository walks the whole protocol a stage at
a time against a real lock, and is read-only unless asked otherwise.

.. note::

   Two things to know when reaching for this.

   A lock is matched by the MAC in its manufacturer data, not by its
   advertised name. Two locks both advertise as ``SCHLAGE...``, and a lock
   that is not the one whose SAT you hold answers the handshake's first step
   and then goes silent, which is indistinguishable from a protocol bug.
   :func:`discover` cannot do this matching, since it filters on a service
   UUID the locks do not advertise; the probe shows what does work.

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
