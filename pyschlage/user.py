"""Objects related to Schlage API users."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

from . import payload


@dataclass
class User:
    """A Schlage API user account."""

    name: str | None = None
    """The username associated with the account."""

    email: str = ""
    """The email associated with the account."""

    user_id: str = field(default="", repr=False)
    """Unique identifier for the user."""

    role: str | None = None
    """The user's role for the lock (e.g. ``"owner"`` or ``"guest"``)."""

    @classmethod
    def from_json(cls, json: dict[str, Any]) -> User:
        """Creates a User from a JSON dict.

        :meta private:
        """
        user_json = cast(payload.UserJson, json)
        return cls(
            name=user_json.get("friendlyName"),
            email=user_json["email"],
            user_id=user_json["identityId"],
            role=user_json.get("role"),
        )
