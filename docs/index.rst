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

-------------------

Basic usage
===========

.. code-block:: python

    >>> from pyschlage import Auth, Schlage
    >>> # Create a Schlage object and authenticate with your credentials.
    >>> s = Schlage(Auth("username", "password"))
    >>> # List the locks attached to your account.
    >>> locks = s.locks()
    >>> # Print the name of the first lock
    >>> print(locks[0].name)
    'My lock'
    >>> # Lock the first lock.
    >>> locks[0].lock()


Managing access codes
======================

.. code-block:: python

    >>> from pyschlage.code import AccessCode
    >>> lock = locks[0]
    >>> # Add a new access code to a lock.
    >>> guest_code = AccessCode(name="Guest", code="1234")
    >>> lock.add_access_code(guest_code)
    >>> # List the access codes currently on the lock.
    >>> lock.refresh_access_codes()
    >>> for access_code in lock.access_codes.values():
    ...     print(access_code.name, access_code.code)
    ...
    Guest 1234
    >>> # Remove an access code from the lock.
    >>> guest_code.delete()


Reading activity logs
======================

.. code-block:: python

    >>> # Fetch the 10 most recent log entries, newest first.
    >>> for log_entry in lock.logs(limit=10, sort_desc=True):
    ...     print(log_entry.created_at, log_entry.message)


Handling errors
================

All requests to the Schlage cloud service can raise
:mod:`exceptions <pyschlage.exceptions>`.

.. code-block:: python

    >>> from pyschlage.exceptions import NotAuthorizedError, UnknownError
    >>> try:
    ...     locks = s.locks()
    ... except NotAuthorizedError:
    ...     print("Invalid username or password.")
    ... except UnknownError as ex:
    ...     print(f"Something went wrong: {ex}")


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
