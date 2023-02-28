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

## Documentation

API reference can be found on [Read the Docs](https://pyschlage.readthedocs.io)
