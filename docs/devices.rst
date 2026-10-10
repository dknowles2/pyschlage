Supported devices
=================

Schlage's cloud service speaks the same API for every lock on an account,
so :meth:`Schlage.locks() <pyschlage.Schlage.locks>` returns a
:class:`~pyschlage.lock.Lock` for any model the service knows about. What
differs between models is which attributes the lock reports and which
settings it accepts.


Lock models
-----------

``Lock.device_type`` carries the service's ``devicetypeId``. Its prefix
identifies the product:

.. list-table::
   :header-rows: 1
   :widths: 34 12 14 40

   * - Product
     - Model
     - Prefix
     - :class:`~pyschlage.device.DeviceType`
   * - Schlage Encode
     - BE489
     - ``be489``
     - ``ENCODE``
   * - Schlage Encode Plus
     - BE499
     - ``be499``
     - ``ENCODE_PLUS``
   * - Schlage Encode Lever
     - FE789
     - ``fe789``
     - ``ENCODE_LEVER``
   * - Schlage Arrive
     - BE459
     - ``be459``
     - ``ARRIVE``
   * - Schlage Sense Pro
     - BE889
     - ``be889``
     - ``SENSE_PRO``
   * - Schlage Sense
     - BE479
     - ``be479``
     - ``SENSE``
   * - Gainsborough Selene Entrance
     - GSELENT
     - ``gselent``
     - ``GAINSBOROUGH_SELENE_ENTRANCE``
   * - Gainsborough Selene Secure
     - GSELSEC
     - ``gselsec``
     - ``GAINSBOROUGH_SELENE_SECURE``
   * - Schlage Selene Entrance
     - SSELENT
     - ``sselent``
     - ``SCHLAGE_SELENE_ENTRANCE``
   * - Schlage Selene Secure
     - SSELSEC
     - ``sselsec``
     - ``SCHLAGE_SELENE_SECURE``
   * - Wi-Fi Adapter
     - BR400
     - ``br400``
     - ``BRIDGE``

The Wi-Fi Adapter is a separate device that gives a Sense cloud
connectivity. :meth:`Schlage.locks() <pyschlage.Schlage.locks>` asks the
service for locks only, so an adapter is never returned as a
:class:`~pyschlage.lock.Lock` even though ``DeviceType.BRIDGE`` exists.

After the prefix comes a transport suffix and, on later hardware, a
generation number:

``be489``
    The family, with no transport in the identifier.
``be489ble``, ``be489wifi``
    First generation, currently reachable over Bluetooth or over Wi-Fi.
``be489wb2``, ``be489ble2``, ``be489wifi2``
    Second generation, same three forms.
``be489wb3``, ``be489ble3``, ``be489wifi3``
    Third generation.

Encode has three generations, Encode Plus and Encode Lever two, and the
rest one. Sense has no suffixes at all: it is always ``be479``.

A lock whose suffix is ``ble`` has been switched to Bluetooth and is not
talking to the cloud. Its device document still exists, so reads return
whatever it last reported, which may be very stale.


Feature support
---------------

``pyschlage`` does not filter by model. Where the table says a setting is
unsupported, the call will still be sent and the lock will reject or
ignore it.

.. list-table::
   :header-rows: 1
   :widths: 32 15 11 12 11 11

   * -
     - Encode family [1]_
     - Arrive
     - Sense Pro
     - Selene
     - Sense
   * - Lock state and battery
     - yes
     - yes
     - yes
     - yes
     - yes
   * - :meth:`~pyschlage.lock.Lock.lock` /
       :meth:`~pyschlage.lock.Lock.unlock`
     - yes
     - yes
     - yes
     - yes
     - command [2]_
   * - Access codes
     - yes
     - yes
     - yes
     - yes
     - yes
   * - :meth:`~pyschlage.lock.Lock.logs`
     - yes
     - yes
     - yes
     - limited [3]_
     - limited [3]_
   * - :meth:`~pyschlage.lock.Lock.set_auto_lock_time`
     - yes [4]_
     - yes [4]_
     - yes [4]_
     - yes [4]_
     - yes [4]_
   * - :meth:`~pyschlage.lock.Lock.set_beeper`
     - yes
     - yes
     - yes
     - yes
     - yes
   * - :meth:`~pyschlage.lock.Lock.set_lock_and_leave`
     - yes
     - yes
     - no
     - no
     - yes
   * - ``alarm_mode``, ``alarm_sensitivity``
     - yes
     - no
     - yes
     - no [5]_
     - yes

.. [1] Encode, Encode Plus and Encode Lever, which behave almost
   identically.
.. [2] A Sense is not a Wi-Fi lock, so
   :meth:`~pyschlage.lock.Lock.lock` sends a ``changelockstate`` command
   through the Wi-Fi Adapter rather than writing ``lockState`` directly.
.. [3] The log endpoint is the same for every model, but Sense and Selene
   locks may return fewer entries than a large ``limit`` asks for.
.. [4] Every model accepts a different set of delays. See
   `Auto-lock delays`_.
.. [5] Selene locks have a simple on/off alarm rather than the modes and
   sensitivity levels the other models expose, so ``alarm_mode`` does not
   mean the same thing there.

Attributes a lock does not report are simply ``None``; nothing raises.
``door_state`` is the clearest example — it is only meaningful on a lock
fitted with a door position sensor, and reads ``DoorState.UNKNOWN``
otherwise.


Capabilities negotiated per lock
--------------------------------

Three capabilities are not fixed by model: the lock advertises them in a
``supportedFeatures`` attribute. ``pyschlage`` has no field for it, but it
does appear in :meth:`~pyschlage.lock.Lock.get_diagnostics`.

``vlac``
    Variable-length access codes. Without it, every code on the lock must
    be exactly ``access_code_length`` digits, fixed when the lock was set
    up. With it, each code may be 4 to 8 digits. Sense Pro always has it.
``scheduledLocking``
    Locking on a schedule. Encode Plus also needs firmware 4 or later.
    ``pyschlage`` does not implement scheduled locking.
``activityAlarm``
    The activity alarm. A lock connected over Bluetooth instead needs
    firmware 11 or later on a first-generation Encode, or 3 or later on a
    second-generation Encode or Encode Lever.


Auto-lock delays
----------------

:data:`~pyschlage.lock.AUTO_LOCK_TIMES` is the union of every model's
list, so :meth:`~pyschlage.lock.Lock.set_auto_lock_time` accepts values a
given lock will reject:

======================  =================================================
Model                   Delays (seconds)
======================  =================================================
Encode, Arrive, Selene  0, 15, 30, 60, 120, 240, 360, 600
Encode Plus             0, 15, 30, 60, 120, 240, 300
Encode Lever            0, 5, 15, 30, 60, 120, 240, 360, 600
Sense                   0, 15, 30, 60, 120, 240
Sense Pro               0, 30, 60, 120, 300, 600, 900, 1800
======================  =================================================

``0`` disables auto-locking. Only Encode Lever accepts 5 seconds, and only
Sense Pro accepts 900 or 1800.


Not implemented
---------------

The service supports several things ``pyschlage`` has no API for:

- **Credentials** (key fobs and NFC), exposed at
  ``devices/{id}/storage/fob/``.
- **Scheduled locking**, carried in the ``scheduleParams`` attribute.
- **Linked locks**, the Selene feature that pairs two locks on one door.
- **Firmware updates**.
- **Commissioning** a new lock, which needs Bluetooth.

Bluetooth is not implemented at all. ``pyschlage`` only talks to the cloud
service, so a lock that has been switched to Bluetooth is effectively
read-only and out of date.
