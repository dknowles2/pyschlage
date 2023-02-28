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

.. autoclass:: pyschlage.code.AccessCode
   :members:
   :undoc-members:

.. autoclass:: pyschlage.code.TemporarySchedule
   :members:
   :undoc-members:

.. autoclass:: pyschlage.code.RecurringSchedule
   :members:
   :undoc-members:

.. autoclass:: pyschlage.code.DaysOfWeek
   :members:
   :undoc-members:

.. autoclass:: pyschlage.log.LockLog
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
