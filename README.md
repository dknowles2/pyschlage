# pyschlage
Python 3 library for interacting with Schlage WiFi locks.

*Note that this project has no official relationship with Schlage or Allegion. Use at your own risk.*

## Usage

```python
from pyschlage import Auth, Schlage

# Create a Schlage object and authenticate with your credentials.
s = Schlage(Auth("username", "password"))

# List the devices attached to your account.
devices = s.get_devices()

# Print the name of the first device
print(devices[0].name)
"My lock"

# Lock the first device.
devices[0].lock()
```
