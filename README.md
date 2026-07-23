# pyschlage
Python 3 library for interacting with Schlage Encode WiFi locks.

*Note that this project has no official relationship with Schlage or Allegion. Use at your own risk.*

## Usage

### Basic usage

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
locks[0].lock()
```

### Managing access codes

```python
from pyschlage.code import AccessCode

lock = locks[0]

# Add a new access code to a lock.
guest_code = AccessCode(name="Guest", code="1234")
lock.add_access_code(guest_code)

# List the access codes currently on the lock.
lock.refresh_access_codes()
for access_code in lock.access_codes.values():
    print(access_code.name, access_code.code)

# Remove an access code from the lock.
guest_code.delete()
```

### Reading activity logs

```python
# Fetch the 10 most recent log entries, newest first.
for log_entry in lock.logs(limit=10, sort_desc=True):
    print(log_entry.created_at, log_entry.message)
```

### Handling errors

All requests to the Schlage cloud service can raise
[`pyschlage.exceptions`](https://pyschlage.readthedocs.io/en/latest/api.html#exceptions):

```python
from pyschlage.exceptions import NotAuthorizedError, UnknownError

try:
    locks = s.locks()
except NotAuthorizedError:
    print("Invalid username or password.")
except UnknownError as ex:
    print(f"Something went wrong: {ex}")
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
