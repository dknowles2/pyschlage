API Reference
=============


Main API
--------

The main entry-point into pyschlage is the
:class:`pyschlage.Schlage <pyschlage.Schlage>` client, which owns all
communication with the cloud service. Model objects returned by the client are
immutable snapshots; methods that change a lock return the updated object
rather than modifying the one passed in.

.. autofunction:: pyschlage.connect

.. autoclass:: pyschlage.Schlage
   :members:
   :special-members: __init__


Authentication
--------------

:func:`pyschlage.connect` and
:meth:`Schlage.authenticate() <pyschlage.Schlage.authenticate>` build an
:class:`pyschlage.Auth <pyschlage.Auth>` for you. Construct one directly only
when supplying a custom :class:`Transport <pyschlage.Transport>`.

.. autoclass:: pyschlage.Auth
   :members:
   :special-members: __init__


Transport
---------

The client reaches the network through a
:class:`Transport <pyschlage.Transport>`. Implement the protocol to route
requests differently or to stub out HTTP entirely in tests.

.. autoclass:: pyschlage.Transport
   :members:

.. autoclass:: pyschlage.AiohttpTransport
   :members:
   :special-members: __init__


Locks
-----

.. autoclass:: pyschlage.lock.Lock
   :members:
   :undoc-members:

.. autoclass:: pyschlage.lock.LockStateMetadata
   :members:
   :undoc-members:

.. autodata:: pyschlage.lock.AUTO_LOCK_TIMES


Access codes
------------

Access codes that already exist on a lock are represented by
:class:`AccessCode <pyschlage.code.AccessCode>`. To add one, build a
:class:`NewAccessCode <pyschlage.code.NewAccessCode>` and pass it to
:meth:`Schlage.add_access_code() <pyschlage.Schlage.add_access_code>`. To
change an existing code, copy it with :func:`dataclasses.replace` and pass the
copy to
:meth:`Schlage.update_access_code() <pyschlage.Schlage.update_access_code>`.

.. autoclass:: pyschlage.code.NewAccessCode
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


Logs
----

.. autoclass:: pyschlage.log.LockLog
   :members:
   :undoc-members:


Users
-----

The :class:`Schlage <pyschlage.Schlage>` object's
:meth:`get_users() <pyschlage.Schlage.get_users>` method, as well as the
:attr:`Lock.users <pyschlage.lock.Lock.users>` attribute, return
:class:`User <pyschlage.user.User>` objects.

.. autoclass:: pyschlage.user.User
   :members:
   :undoc-members:


Notifications
-------------

.. autoclass:: pyschlage.notification.Notification
   :members:
   :undoc-members:


Exceptions
----------

.. automodule:: pyschlage.exceptions
   :members:
   :undoc-members:

.. toctree::
   :maxdepth: 2
   :caption: Contents:
