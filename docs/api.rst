API Reference
=============


Main API
--------

The main entry-point into pyschlage is through the
:class:`pyschlage.Schlage <pyschlage.Schlage>` object.
From there you can access the locks associated with a
Schlage account, and interact with them directly.

.. autoclass:: pyschlage.Schlage
   :members:
   :special-members: __init__


Authentication
--------------

Creating a :class:`Schlage <pyschlage.Schlage>`
object first requires creating an authentication and
transport object, which is encapsulated in the
:class:`pyschlage.Auth <pyschlage.Auth>` object.

.. autoclass:: pyschlage.Auth
   :members:
   :special-members: __init__


Locks
-----

The :class:`Schlage <pyschlage.Schlage>` object
provides access to :class:`Lock <pyschlage.lock.Lock>`
objects. Each instance of a :class:`Lock <pyschlage.lock.Lock>`
itself can fetch additional data such as
:class:`access codes <pyschlage.code.AccessCode>` and
:class:`log entries <pyschlage.log.LockLog>`.

.. autoclass:: pyschlage.lock.Lock
   :members:
   :undoc-members:
   :inherited-members:

.. autoclass:: pyschlage.lock.LockStateMetadata
   :members:
   :undoc-members:

.. autoclass:: pyschlage.code.AccessCode
   :members:
   :undoc-members:

.. autoclass:: pyschlage.code.RecurringSchedule
   :members:
   :undoc-members:

.. autoclass:: pyschlage.code.MultiRecurringSchedule
   :members:
   :undoc-members:

.. autoclass:: pyschlage.code.TemporarySchedule
   :members:
   :undoc-members:

.. autoclass:: pyschlage.code.DaysOfWeek
   :members:
   :undoc-members:

.. autoclass:: pyschlage.log.LockLog
   :members:
   :undoc-members:


Device attributes
-----------------

Several :class:`Lock <pyschlage.lock.Lock>` attributes are reported as
enumerations. Values the lock reports that are not listed here are mapped
to ``UNKNOWN``.

.. autoclass:: pyschlage.device.DeviceType
   :members:
   :undoc-members:

.. autoclass:: pyschlage.device.AlarmMode
   :members:
   :undoc-members:

.. autoclass:: pyschlage.device.BatteryState
   :members:
   :undoc-members:

.. autoclass:: pyschlage.device.LockState
   :members:
   :undoc-members:

.. autoclass:: pyschlage.device.DoorState
   :members:
   :undoc-members:

.. autoclass:: pyschlage.device.OperatingMode
   :members:
   :undoc-members:


Users
-----

The :class:`Schlage <pyschlage.Schlage>` object's
:meth:`users() <pyschlage.Schlage.users>` method, as well as the
:attr:`Lock.users <pyschlage.lock.Lock.users>` attribute, return
:class:`User <pyschlage.user.User>` objects.

.. autoclass:: pyschlage.user.User
   :members:
   :undoc-members:


Asynchronous API
----------------

:mod:`pyschlage.aio` is an asynchronous equivalent of the API above, for
callers running inside an event loop. It is a separate surface rather than a
replacement: the synchronous API is unchanged and both are supported.

It differs in shape as well as in being awaitable. The models are immutable
snapshots that only hold state, and the
:class:`Schlage <pyschlage.aio.Schlage>` client owns every request; a method
that changes a lock returns the updated snapshot rather than modifying the one
it was given. Two snapshots describing the same state compare equal, so a
caller can cheaply tell whether anything changed.

.. code-block:: python

    import pyschlage.aio

    async with pyschlage.aio.connect("username", "password") as schlage:
        locks = await schlage.get_locks()
        locked = await schlage.set_locked(locks[0], True)

.. autoclass:: pyschlage.aio.Schlage
   :members:
   :special-members: __init__

.. autofunction:: pyschlage.aio.connect

.. autoclass:: pyschlage.aio.Lock
   :members:
   :undoc-members:

.. autoclass:: pyschlage.aio.AccessCode
   :members:
   :undoc-members:

.. autoclass:: pyschlage.aio.NewAccessCode
   :members:
   :undoc-members:

.. autoclass:: pyschlage.aio.Notification
   :members:
   :undoc-members:

Lock writes go through a :class:`LockBackend <pyschlage.aio.LockBackend>`,
which is how the library reaches a lock to change it. The cloud service is one
way; a direct Bluetooth LE connection will be another. Both take and return
snapshots, so a caller cannot tell from the result which way it went. Only the
operations every backend can carry out live there — access codes, logs, users
and notifications are cloud-only and stay on
:class:`Schlage <pyschlage.aio.Schlage>`.

.. autoclass:: pyschlage.aio.LockBackend
   :members:

.. autoclass:: pyschlage.aio.CloudBackend
   :members:
   :special-members: __init__

.. autoclass:: pyschlage.aio.Setting
   :members:
   :undoc-members:

The network seam is a :class:`Transport <pyschlage.aio.Transport>`. Supply an
implementation of it to :meth:`Schlage.from_transport
<pyschlage.aio.Schlage.from_transport>` to reach the service some other way,
or to stub out HTTP entirely in tests.

.. autoclass:: pyschlage.aio.Transport
   :members:

.. autoclass:: pyschlage.aio.AiohttpTransport
   :members:
   :special-members: __init__


Bluetooth LE
------------

.. warning::

   None of this has been exercised against a real lock. See
   :mod:`pyschlage.ble`.

Locks speak Google's uWeave over Bluetooth LE: CBOR-encoded RPC records over
two GATT characteristics, inside an AES-EAX session authorized by macaroons
the cloud service issues. ``PROTOCOL.md`` in the repository documents what is
known of the protocol.

:func:`pyschlage.ble.connect` connects to a lock, runs the session handshake
and yields a :class:`BleBackend <pyschlage.ble.BleBackend>`, which is a
:class:`LockBackend <pyschlage.aio.LockBackend>` like any other. It needs the
lock's ``SAT`` and ``CAT`` tokens, which come from the cloud service as hex.

.. code-block:: python

    import pyschlage.ble

    async with pyschlage.ble.connect(
        device, sat=sat, cat=cat, user_id=schlage.user_id
    ) as ble:
        locked = await ble.set_locked(lock, True)

.. autofunction:: pyschlage.ble.connect

.. autofunction:: pyschlage.ble.discover

.. autoclass:: pyschlage.ble.BleBackend
   :members:
   :special-members: __init__

.. autoclass:: pyschlage.ble.Session
   :members:
   :special-members: __init__

.. autoclass:: pyschlage.ble.GattChannel
   :members:
   :special-members: __init__


Exceptions
----------

.. automodule:: pyschlage.exceptions
   :members:
   :undoc-members:

.. toctree::
   :maxdepth: 2
   :caption: Contents:
