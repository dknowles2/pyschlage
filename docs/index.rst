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
-----------

    >>> from pyschlage import Auth, Schlage
    >>> # Create a Schlage object and authenticate with your credentials.
    >>> s = Schlage(Auth("username", "password"))
    >>> # List the locks attached to your account.
    >>> locks = s.locks()
    >>> # Print the name of the first lock
    >>> print(locks[0].name)
    'My lock'
    >>> # Lock the first lock.
    >>> lock[0].lock()

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   installation
   api/index


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
