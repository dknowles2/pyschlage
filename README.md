# pyschlage
Python 3 library for interacting with Schlage Encode WiFi locks.

*Note that this project has no official relationship with Schlage or Allegion. Use at your own risk.*

> **pyschlage 2.0 is async-only and is not backwards compatible with 1.x.**
> The synchronous API is frozen and no longer developed. Pin `pyschlage<2027`
> to stay on it; see [Migrating from 1.x](#migrating-from-1x) below.

## Usage

### Basic usage

```python
import asyncio
import pyschlage


async def main():
    async with pyschlage.connect("username", "password") as schlage:
        # List the locks attached to your account.
        locks = await schlage.get_locks()

        # Print the name of the first lock.
        print(locks[0].name)
        "My lock"

        # Lock the first lock. This returns the updated lock.
        lock = await schlage.set_locked(locks[0], True)
        print(lock.is_locked)
        True


asyncio.run(main())
```

If you already manage an `aiohttp.ClientSession` (as Home Assistant does),
pass it in and it will not be closed for you:

```python
schlage = await pyschlage.Schlage.authenticate("username", "password", session=session)
```

### Immutable state

Locks and access codes are frozen dataclasses — snapshots of what the service
reported. Nothing mutates in place; methods that change a lock return a new
one. To modify an object, build a copy with `dataclasses.replace`:

```python
from dataclasses import replace

renamed = replace(access_code, name="Dog walker")
await schlage.update_access_code(renamed)
```

Because they're frozen, snapshots compare cheaply with `==`, which makes it
easy to skip work when nothing has changed.

### Managing access codes

```python
from pyschlage import NewAccessCode

lock = locks[0]

# Add a new access code to a lock.
code = await schlage.add_access_code(lock, NewAccessCode(name="Guest", code="1234"))

# List the access codes currently on the lock.
for access_code in await schlage.get_access_codes(lock):
    print(access_code.name, access_code.code)

# Remove an access code from the lock.
await schlage.delete_access_code(code)
```

### Reading activity logs

```python
# Fetch the 10 most recent log entries, newest first.
for log_entry in await schlage.get_logs(lock, limit=10, sort_desc=True):
    print(log_entry.created_at, log_entry.message)
```

### Fetching concurrently

Independent requests can be issued in parallel:

```python
locks = await schlage.get_locks()
codes = await asyncio.gather(*(schlage.get_access_codes(lock) for lock in locks))
```

### Handling errors

All requests to the Schlage cloud service can raise
[`pyschlage.exceptions`](https://pyschlage.readthedocs.io/en/latest/api.html#exceptions):

```python
from pyschlage.exceptions import NotAuthorizedError, UnknownError

try:
    locks = await schlage.get_locks()
except NotAuthorizedError:
    print("Invalid username or password.")
except UnknownError as ex:
    print(f"Something went wrong: {ex}")
```

## Migrating from 1.x

Every call is now `async`, and all I/O lives on the `Schlage` client rather
than on the model objects.

| 1.x | 2.0 |
| --- | --- |
| `Schlage(Auth(user, pw))` | `await Schlage.authenticate(user, pw)` or `pyschlage.connect(...)` |
| `s.locks()` | `await s.get_locks()` |
| `s.users()` | `await s.get_users()` |
| `lock.refresh()` | `lock = await s.get_lock(lock)` |
| `lock.lock()` / `lock.unlock()` | `lock = await s.set_locked(lock, True/False)` |
| `lock.set_beeper(x)` | `lock = await s.set_beeper(lock, x)` |
| `lock.logs(...)` | `await s.get_logs(lock, ...)` |
| `lock.keypad_disabled()` | `await s.keypad_disabled(lock)` |
| `lock.access_codes` / `lock.refresh_access_codes()` | `await s.get_access_codes(lock)` |
| `lock.add_access_code(AccessCode(...))` | `await s.add_access_code(lock, NewAccessCode(...))` |
| `code.save()` | `await s.update_access_code(code)` |
| `code.delete()` | `await s.delete_access_code(code)` |
| `lock.last_changed_by(logs)` | `lock.last_changed_by()` |

Other changes worth knowing about:

- **`NotAuthenticatedError` is gone.** A client always has credentials, so the
  error had nothing to signal. Authentication failures raise
  `NotAuthorizedError`, which now also covers HTTP 401/403 responses.
- **New codes use a distinct type.** `NewAccessCode` has no id; the
  `AccessCode` returned by `add_access_code` does. This replaces the old
  `access_code_id is None` check.
- **Access codes no longer hang off the lock.** `Lock.access_codes` is gone;
  fetch them with `get_access_codes(lock)`.
- **Bridge-attached (non-WiFi) locks return optimistic state.** The
  `changelockstate` command reports no device state, so the `Lock` returned by
  `set_locked` reflects the request. Call `get_lock()` to confirm.

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
