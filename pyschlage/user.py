"""Objects related to Schlage API users."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class User:
    """A Schlage API user account."""

    name: str | None = None
    """The username associated with the account."""

    email: str = ""
    """The email associated with the account."""

    user_id: str = field(default="", repr=False)
    """Unique identifier for the user."""

    @classmethod
    def from_json(cls, json) -> User:
        """Creates a User from a JSON dict.

        :meta private:
        """
        return User(
            name=json.get("friendlyName"),
            email=json["email"],
            user_id=json["identityId"],
        )
