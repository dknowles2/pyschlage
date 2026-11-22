from __future__ import annotations

from pyschlage.user import User


def test_from_json(lock_users_json: list[dict]):
    owner = User(
        name="asdf",
        email="asdf@asdf.com",
        user_id="user-uuid",
        role="owner",
    )
    guest = User(
        name="Foo Bar",
        email="foo@bar.xyz",
        user_id="foo-bar-uuid",
        role="guest",
    )
    assert User.from_json(lock_users_json[0]) == owner
    assert User.from_json(lock_users_json[1]) == guest


def test_from_json_no_name(lock_users_json: list[dict]):
    for user_json in lock_users_json:
        user_json.pop("friendlyName")
        assert User.from_json(user_json).name is None


def test_from_json_no_role(lock_users_json: list[dict]):
    for user_json in lock_users_json:
        user_json.pop("role")
        assert User.from_json(user_json).role is None
