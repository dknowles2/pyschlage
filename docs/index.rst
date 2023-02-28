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
    >>> lock[0].lock()


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
