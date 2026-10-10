"""Bluetooth LE support for Schlage locks.

The locks speak Google's uWeave: CBOR-encoded RPC records over two GATT
characteristics, inside an AES-EAX session authorized by macaroons the cloud
service issues. ``PROTOCOL.md`` documents what is known of it.

This package needs the ``ble`` extra::

    pip install pyschlage[ble]

This has been exercised against real locks. A BE489WB ran the whole protocol
end to end: the handshake, an authorized session, trait and settings reads,
the lock-state read, and locking and unlocking the bolt. A BE499WB2 ran
everything but the bolt.

``scripts/ble_probe.py`` in the repository walks the whole protocol a stage at
a time against a real lock, and is read-only unless asked otherwise.

.. note::

   Two things to know when reaching for this.

Use :func:`find_lock` rather than matching on anything yourself. It takes
   two identifiers because neither works everywhere: a BE489WB advertises the
   MAC the cloud reports, while a BE499WB2 advertises its Bluetooth radio's
   address instead and is identifiable only by the name it derives from its
   serial number. Matching on a name merely looking Schlage-ish is worse than
   not matching at all -- a lock that is not the one whose SAT you hold
   answers the handshake's first step and then goes silent, which is
   indistinguishable from a protocol bug.

   A record the lock sends that fails to decrypt, or that arrives
   unexpectedly, advances the receive counter and desynchronises the session
   for good. The app behaves the same way, so this may be inherent; recovery
   is a new session.
"""

from .backend import (
    BleBackend,
    GattChannel,
    advertised_mac,
    advertised_name,
    connect,
    discover,
    find_lock,
    matches,
)
from .session import Session

__all__ = (
    "BleBackend",
    "GattChannel",
    "Session",
    "advertised_mac",
    "advertised_name",
    "connect",
    "discover",
    "find_lock",
    "matches",
)
