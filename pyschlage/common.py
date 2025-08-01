"""Common utilities and classes."""

from __future__ import annotations

from abc import abstractmethod
from copy import deepcopy
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from threading import Lock as Mutex
from time import mktime
from typing import Any

from .auth import Auth
from .exceptions import NotAuthenticatedError


@dataclass
class Mutable:
    """Base class for models which have mutable state."""

    _mu: Mutex = field(init=False, repr=False, compare=False, default_factory=Mutex)
    _auth: Auth | None = field(default=None, repr=False)

    @classmethod
    @abstractmethod
    def from_json(cls, auth: Auth, json: dict[str, Any], *args, **kwargs) -> Mutable:
        """Creates a new instance from a JSON dict."""
        raise NotImplementedError

    def __getstate__(self):
        state = self.__dict__.copy()
        del state["_mu"]
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self._mu = Mutex()

    def _update_with(self, json, *args, **kwargs):
        if self._auth is None:
            raise NotAuthenticatedError
        new_obj = self.__class__.from_json(self._auth, json, *args, **kwargs)
        with self._mu:
            for f in fields(new_obj):
                setattr(self, f.name, getattr(new_obj, f.name))


def utc2local(utc: datetime) -> datetime:
    """Converts a UTC datetime to localtime."""
    epoch = mktime(utc.timetuple())
    offset = datetime.fromtimestamp(epoch) - datetime.fromtimestamp(epoch, UTC).replace(
        tzinfo=None
    )
    return (utc + offset).replace(tzinfo=None)


def fromisoformat(dt: str) -> datetime:
    """Converts an ISO formatted datetime into a datetime object."""
    # datetime.fromisoformat() doesn't like fractional seconds with a "Z" suffix.
    return datetime.fromisoformat(dt.rstrip("Z") + "+00:00")


def redact(json: dict[Any, Any], *, allowed: list[str]) -> dict[str, Any]:
    """Returns a copy of the given JSON dict with non-allowed keys redacted."""
    if len(allowed) == 1 and allowed[0] == "*":
        return deepcopy(json)

    allowed_here: dict[str, list[str]] = {}
    for allow in allowed:
        k, _, children = allow.partition(".")
        if k not in allowed_here:
            allowed_here[k] = []
        if not children:
            children = "*"
        allowed_here[k].append(children)

    ret: dict[str, Any] = {}
    for k, v in json.items():
        if isinstance(v, dict):
            ret[k] = redact(v, allowed=allowed_here.get(k, []))
        elif k in allowed_here:
            ret[k] = v
        else:
            if isinstance(v, list):
                ret[k] = ["<REDACTED>"]
            else:
                ret[k] = "<REDACTED>"
    return ret
