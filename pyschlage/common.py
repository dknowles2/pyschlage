"""Common utilities shared by the pyschlage models."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any


def fromisoformat(dt: str) -> datetime:
    """Converts an ISO formatted datetime into a datetime object."""
    return datetime.fromisoformat(dt)


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
