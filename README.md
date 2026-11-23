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

## Reporting a new lock model

If pyschlage doesn't work correctly with your lock, the bundled diagnostics
tool collects everything needed to add support for it:

```sh
$ python -m pyschlage.diagnostics
```

It checks the API calls pyschlage relies on, actuates the lock using both of
the lock state transports pyschlage knows about (which is how unsupported
WiFi models are identified), toggles each setting and adds and removes a
temporary access code, restoring the original state as it goes.

It then writes two files: a Markdown report to paste into an
[issue](https://github.com/dknowles2/pyschlage/issues), and a redacted JSON
report to attach to it. The Markdown report holds a feature support table for
each lock and the pyschlage changes needed for full support:

```markdown
### BE999WB (`be999wifi`)

| Field | Value |
| --- | --- |
| Known to pyschlage | no |
| Treated as a WiFi lock | no |
| Working lock state transports | wifi |

#### Feature support

| Feature | Supported | Notes |
| --- | --- | --- |
| Lock state | supported | reported as locked |
| Activity logs | supported | 1 entry(s) |
| Lock/unlock (WiFi attributes) | supported | unlocked accepted, confirmed=True |
| Lock/unlock (bridge command) | unsupported | UnknownError: command not found changelockstate |

#### pyschlage changes needed for full support

- add device type 'be999' ('be999wifi') to pyschlage.device.DeviceType
- treat 'be999' as a WiFi lock: add it to _WIFI_DEVICE_TYPE_PREFIXES in pyschlage/lock.py
```

Because the run modifies the lock, it asks for confirmation first and warns
loudly if it cannot restore something. Pass `--read-only` to collect the
report without touching the lock:

```sh
$ python -m pyschlage.diagnostics --read-only
```

Credentials are read from `$SCHLAGE_USERNAME` and `$SCHLAGE_PASSWORD` if set,
and prompted for otherwise. Run `--help` for the remaining options.

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
