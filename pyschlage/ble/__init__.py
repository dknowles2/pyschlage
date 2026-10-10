"""Bluetooth LE support for Schlage locks.

The locks speak Google's uWeave: CBOR-encoded RPC records over two GATT
characteristics, inside an AES-EAX session authorized by macaroons the cloud
service issues. ``PROTOCOL.md`` documents what is known of it.

This package needs the ``ble`` extra::

    pip install pyschlage[ble]

This has been exercised against real locks. A BE489WB and a BE499WB2 each ran
the whole protocol: discovery, the handshake, an authorized session, trait and
settings reads, the lock-state read, locking and unlocking the bolt, and
writing a setting and putting it back.

Two paths have never run against hardware. Minting a fresh CAT has not,
because both locks left the flag asking for one clear on every attempt. And
access codes, logs and commissioning are not implemented at all, their
parameters never having been established.

``scripts/ble_probe.py`` in the repository walks the whole protocol a stage at
a time against a real lock, and is read-only unless asked otherwise.

.. note::

   Two things to know when reaching for this.

Use :func:`find_lock` rather than matching on anything yourself. It takes
   three identifiers because none works everywhere. A BE489WB advertises the
   address in ``macAddress``; an Encode Plus advertises its Bluetooth radio's
   instead, which the cloud reports separately as
   :attr:`~pyschlage.aio.Lock.device_uid`; and failing both there is the name
   a lock derives from its serial, which is an observation with no second
   source and is not always advertised at all. Matching on a name merely
   looking Schlage-ish is worse than not matching -- a lock that is not the
   one whose SAT you hold answers the handshake's first step and then goes
   silent, which is indistinguishable from a protocol bug.

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
