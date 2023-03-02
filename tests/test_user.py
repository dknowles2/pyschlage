from unittest import mock

from pyschlage.user import User


def test_from_json(lock_users_json):
    user = User(
        name="asdf",
        email="asdf@asdf.com",
        user_id="user-uuid",
    )
    assert User.from_json(lock_users_json[0]) == user
