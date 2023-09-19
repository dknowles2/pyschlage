from __future__ import annotations

from pyschlage.user import User


def test_from_json(lock_users_json: list[dict]):
    user = User(
        name="asdf",
        email="asdf@asdf.com",
        user_id="user-uuid",
    )
    assert User.from_json(lock_users_json[0]) == user


def test_from_json_no_name(lock_users_json: list[dict]):
    for user_json in lock_users_json:
        user_json.pop("friendlyName")
        assert User.from_json(user_json).name is None
