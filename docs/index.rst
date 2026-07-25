Pyschlage
=========

.. image:: https://github.com/dknowles2/pyschlage/workflows/Build%20and%20Test/badge.svg
    :target: https://github.com/dknowles2/pyschlage/actions/workflows/build-and-test.yml
    :alt: Build and Test

.. image:: https://img.shields.io/pypi/v/pyschlage.svg
    :target: https://pypi.python.org/pypi/pyschlage

.. image:: https://readthedocs.org/projects/pyschlage/badge/?version=latest
    :target: https://pyschlage.readthedocs.io/en/latest/?badge=latest
    :alt: Documentation Status

.. image:: https://img.shields.io/badge/code%20style-black-000000.svg
    :target: https://github.com/psf/black
    :alt: Black

Pyschlage is a Python 3 library for interacting with Schlage Encode WiFi locks.

.. warning::

   pyschlage 2.0 is async-only and is not backwards compatible with 1.x. The
   synchronous API is frozen and no longer developed. Pin ``pyschlage<2027``
   to stay on it.

-------------------

Basic usage
===========

.. code-block:: python

    import asyncio
    import pyschlage

    async def main():
        async with pyschlage.connect("username", "password") as schlage:
            # List the locks attached to your account.
            locks = await schlage.get_locks()
            # Print the name of the first lock.
            print(locks[0].name)
            # Lock the first lock. This returns the updated lock.
            lock = await schlage.set_locked(locks[0], True)
            print(lock.is_locked)

    asyncio.run(main())

If you already manage an :class:`aiohttp.ClientSession`, pass it in with
``session=`` and it will not be closed for you.


Immutable state
===============

Locks and access codes are frozen dataclasses: snapshots of what the service
reported. Nothing mutates in place, and methods that change a lock return a
new one. Build modified copies with :func:`dataclasses.replace`.

.. code-block:: python

    from dataclasses import replace

    renamed = replace(access_code, name="Dog walker")
    await schlage.update_access_code(renamed)


Managing access codes
======================

.. code-block:: python

    from pyschlage import NewAccessCode

    lock = locks[0]
    # Add a new access code to a lock.
    code = await schlage.add_access_code(
        lock, NewAccessCode(name="Guest", code="1234")
    )
    # List the access codes currently on the lock.
    for access_code in await schlage.get_access_codes(lock):
        print(access_code.name, access_code.code)
    # Remove an access code from the lock.
    await schlage.delete_access_code(code)


Reading activity logs
======================

.. code-block:: python

    # Fetch the 10 most recent log entries, newest first.
    for log_entry in await schlage.get_logs(lock, limit=10, sort_desc=True):
        print(log_entry.created_at, log_entry.message)


Fetching concurrently
=====================

Independent requests can be issued in parallel.

.. code-block:: python

    locks = await schlage.get_locks()
    codes = await asyncio.gather(
        *(schlage.get_access_codes(lock) for lock in locks)
    )


Handling errors
================

All requests to the Schlage cloud service can raise
:mod:`exceptions <pyschlage.exceptions>`.

.. code-block:: python

    from pyschlage.exceptions import NotAuthorizedError, UnknownError

    try:
        locks = await schlage.get_locks()
    except NotAuthorizedError:
        print("Invalid username or password.")
    except UnknownError as ex:
        print(f"Something went wrong: {ex}")


Installation
============

Pip
---

To install pyschlage, run this command in your terminal:

.. code-block:: bash

    $ pip install pyschlage


Source code
-----------

Pyschlage is actively developed on Github, where the code is
`always available <https://github.com/dknowles2/pyschlage>`_.

You can either clone the public repository:

.. code-block:: bash

    $ git clone https://github.com/dknowles2/pyschlage


Or download the latest
`tarball <https://github.com/dknowles2/pyschlage/tarball/main>`_:

.. code-block:: bash

    $ curl -OL https://github.com/dknowles2/pyschlage/tarball/main

Once you have a copy of the source, you can embed it in your own Python
package, or install it into your site-packages easily:

.. code-block:: bash

    $ cd pyschlage
    $ python -m pip install .


API Reference
=============

.. toctree::
   :maxdepth: 2

   api
