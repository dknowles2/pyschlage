"""Objects related to Schlage API users."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class User:
    """A Schlage API user account."""

    name: str = ""
    """The username associated with the account."""

    email: str = ""
    """The email associated with the account."""

    user_id: str | None = field(default=None, repr=False)
    """Unique identifier for the user."""

    @staticmethod
    def request_path(user_id: str | None = None) -> str:
        """Returns the request path for a User.

        :meta private:
        """
        path = "users"
        if user_id:
            return f"{path}/{user_id}"
        return path

    @classmethod
    def from_json(cls, json) -> User:
        """Creates a User from a JSON dict.

        :meta private:
        """
        return User(
            name=json["friendlyName"],
            email=json["email"],
            user_id=json["identityId"],
        )
