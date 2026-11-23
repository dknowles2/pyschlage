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

.. autoclass:: pyschlage.lock.SupportedFeatures
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


Diagnostics
-----------

The :mod:`pyschlage.diagnostics` module runs end-to-end checks against an
account and writes two reports: a Markdown one holding a feature support
table and the pyschlage changes needed for full support, which can be pasted
into a `GitHub issue <https://github.com/dknowles2/pyschlage/issues>`_, and a
redacted JSON one holding the raw device attributes.

.. code-block:: bash

    $ python -m pyschlage.diagnostics

.. automodule:: pyschlage.diagnostics

.. autofunction:: pyschlage.diagnostics.collect

.. autofunction:: pyschlage.diagnostics.main

.. autoclass:: pyschlage.diagnostics.DiagnosticsReport
   :members:
   :undoc-members:

.. autoclass:: pyschlage.diagnostics.LockDiagnostics
   :members:
   :undoc-members:

.. autoclass:: pyschlage.diagnostics.CheckResult
   :members:
   :undoc-members:

.. autoclass:: pyschlage.diagnostics.FeatureSupport
   :members:
   :undoc-members:

.. autoclass:: pyschlage.diagnostics.FeatureStatus
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
