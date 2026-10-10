"""Requests issued against the Schlage WiFi cloud service.

This module is the single place that knows the service's paths, query
parameters and command names. It depends on nothing else in the package, so
that other API layers can reuse the request shapes rather than growing a
second copy of them.

:meta private:
"""

from __future__ import annotations

from typing import Any, NamedTuple

ADD_ACCESS_CODE = "addaccesscode"
"""Command that adds an access code to a lock."""

CHANGE_LOCK_STATE = "changelockstate"
"""Command that locks or unlocks a bridge-attached lock."""

DELETE_ACCESS_CODE = "deleteaccesscode"
"""Command that deletes an access code from a lock."""

UPDATE_ACCESS_CODE = "updateaccesscode"
"""Command that updates an existing access code."""


class Request(NamedTuple):
    """A request against the Schlage WiFi cloud service.

    :meta private:
    """

    method: str
    """The HTTP method to use."""

    path: str
    """The request path, relative to the API root."""

    params: dict[str, Any] | None = None
    """Query parameters, if any."""

    json: Any = None
    """The JSON request body, if any."""

    @property
    def kwargs(self) -> dict[str, Any]:
        """The optional arguments of this request, as keyword arguments.

        :meta private:
        """
        kwargs: dict[str, Any] = {}
        if self.params is not None:
            kwargs["params"] = self.params
        if self.json is not None:
            kwargs["json"] = self.json
        return kwargs


def get_locks() -> Request:
    """Returns a request that fetches all locks in the account.

    :meta private:
    """
    return Request("get", "devices", params={"archetype": "lock"})


def get_lock(device_id: str) -> Request:
    """Returns a request that fetches a single lock.

    :meta private:
    """
    return Request("get", f"devices/{device_id}")


def put_lock_attributes(device_id: str, attributes: dict[str, Any]) -> Request:
    """Returns a request that writes a lock's attributes.

    :meta private:
    """
    return Request("put", f"devices/{device_id}", json={"attributes": attributes})


def send_command(device_id: str, command: str, data: dict[str, Any]) -> Request:
    """Returns a request that sends a command to a device.

    :meta private:
    """
    return Request(
        "post", f"devices/{device_id}/commands", json={"data": data, "name": command}
    )


def change_lock_state(
    device_id: str, *, cat: str, user_id: str, lock_state: int
) -> Request:
    """Returns a request that locks or unlocks a bridge-attached lock.

    :meta private:
    """
    return send_command(
        device_id,
        CHANGE_LOCK_STATE,
        {
            "CAT": cat,
            "deviceId": device_id,
            "state": lock_state,
            "userId": user_id,
        },
    )


def get_logs(
    device_id: str, *, limit: int | None = None, sort_desc: bool = False
) -> Request:
    """Returns a request that fetches a lock's activity logs.

    :meta private:
    """
    params: dict[str, Any] = {}
    if limit:
        params["limit"] = limit
    if sort_desc:
        params["sort"] = "desc"
    return Request("get", f"devices/{device_id}/logs", params=params)


def get_current_user() -> Request:
    """Returns a request that fetches the authenticated user.

    :meta private:
    """
    return Request("get", "users/@me")


def get_users() -> Request:
    """Returns a request that fetches all users of the account's locks.

    :meta private:
    """
    return Request("get", "users")


def get_access_codes(device_id: str) -> Request:
    """Returns a request that fetches a lock's access codes.

    :meta private:
    """
    return Request("get", f"devices/{device_id}/storage/accesscode")


def get_notifications(device_id: str) -> Request:
    """Returns a request that fetches a device's notifications.

    :meta private:
    """
    return Request("get", "notifications", params={"deviceId": device_id})


def save_notification(
    device_id: str | None, notification_json: dict[str, Any], *, exists: bool
) -> Request:
    """Returns a request that creates or updates a notification.

    :meta private:
    """
    return Request(
        "put" if exists else "post",
        "notifications",
        params={"deviceId": device_id},
        json=notification_json,
    )


def delete_notification(notification_id: str) -> Request:
    """Returns a request that deletes a notification.

    :meta private:
    """
    return Request("delete", f"notifications/{notification_id}")
