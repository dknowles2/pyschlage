"""Common utilities and classes."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from threading import Lock as Mutex

from .auth import Auth


@dataclass
class Mutable:
    """Base class for models which have mutable state."""

    _mu: Mutex = field(init=False, repr=False, compare=False, default_factory=Mutex)
    _auth: Auth | None = field(default=None, repr=False)

    def __getstate__(self):
        state = self.__dict__.copy()
        del state["_mu"]
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self._mu = Mutex()

    def _update_with(self, json, *args, **kwargs):
        new_obj = self.__class__.from_json(self._auth, json, *args, **kwargs)
        with self._mu:
            for f in fields(new_obj):
                setattr(self, f.name, getattr(new_obj, f.name))
