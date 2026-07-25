"""Objects related to Schlage API users."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class User:
    """A Schlage API user account."""

    name: str | None = None
    """The username associated with the account."""

    email: str = ""
    """The email associated with the account."""

    user_id: str = field(default="", repr=False)
    """Unique identifier for the user."""

    @classmethod
    def from_json(cls, json: dict[str, Any]) -> User:
        """Creates a User from a JSON dict.

        :meta private:
        """
        return cls(
            name=json.get("friendlyName"),
            email=json["email"],
            user_id=json["identityId"],
        )
