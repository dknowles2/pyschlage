# pyschlage
Python 3 library for interacting with Schlage Encode WiFi locks.

*Note that this project has no official relationship with Schlage or Allegion. Use at your own risk.*

## Usage

```python
from pyschlage import Auth, Schlage

# Create a Schlage object and authenticate with your credentials.
s = Schlage(Auth("username", "password"))

# List the locks attached to your account.
locks = s.locks()

# Print the name of the first lock
print(locks[0].name)
"My lock"

# Lock the first lock.
lock[0].lock()
```

## Installation

### Pip

To install pyschlage, run this command in your terminal:

```sh
$ pip install pyschlage
```

### Source code

Pyschlage is actively developed on Github, where the code is [always available](https://github.com/dknowles2/pyschlage).

You can either clone the public repository:

```sh
$ git clone https://github.com/dknowles2/pyschlage
```

Or download the latest [tarball](https://github.com/dknowles2/pyschlage/tarball/main):

```sh
$ curl -OL https://github.com/dknowles2/pyschlage/tarball/main
```

Once you have a copy of the source, you can embed it in your own Python package, or install it into your site-packages easily:

```sh
$ cd pyschlage
$ python -m pip install .
```

## Documentation

API reference can be found on [Read the Docs](https://pyschlage.readthedocs.io)
