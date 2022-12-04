"""Data model for a Schlage WiFi device."""

from __future__ import annotations

import dataclasses
from threading import Lock as Mutex

from .auth import Auth


@dataclasses.dataclass
class Device:
    """A Schlage WiFi device."""

    _mu: Mutex = dataclasses.field(init=False, repr=False, default_factory=Mutex)
    _auth: Auth | None
    device_id: str
    name: str
    model_name: str
    battery_level: int
    is_locked: bool
    is_jammed: bool
    firmware_version: str

    def __getstate__(self):
        state = self.__dict__.copy()
        del state["_mu"]
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self._mu = Mutex()

    @classmethod
    def from_json(cls, auth, json):
        """Creates a Device from a JSON object."""
        return cls(
            _auth=auth,
            device_id=json["deviceId"],
            name=json["name"],
            model_name=json["modelName"],
            battery_level=json["attributes"]["batteryLevel"],
            is_locked=json["attributes"]["lockState"] == 1,
            is_jammed=json["attributes"]["lockState"] == 2,
            firmware_version=json["attributes"]["mainFirmwareVersion"],
        )

    def _update_with(self, json):
        new_obj = Device.from_json(self._auth, json)
        with self._mu:
            for field in dataclasses.fields(new_obj):
                setattr(self, field.name, getattr(new_obj, field.name))

    def update(self):
        """Updates the current device state."""
        self._update_with(self._auth.request("get", self.device_id).json())

    def _toggle(self, lock_state):
        self._update_with(
            self._auth.request(
                "put", self.device_id, json={"attributes": {"lockState": lock_state}}
            ).json()
        )

    def lock(self):
        """Locks the device."""
        self._toggle(1)

    def unlock(self):
        """Unlocks the device."""
        self._toggle(0)
