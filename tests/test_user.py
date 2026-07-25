from pyschlage.user import User


class TestUser:
    def test_from_json(self, lock_users_json: list[dict]) -> None:
        assert User.from_json(lock_users_json[0]) == User(
            name="asdf", email="asdf@asdf.com", user_id="user-uuid"
        )

    def test_from_json_no_friendly_name(self, lock_users_json: list[dict]) -> None:
        json = lock_users_json[0]
        del json["friendlyName"]
        assert User.from_json(json).name is None

    def test_is_hashable(self, lock_users_json: list[dict]) -> None:
        # Frozen dataclasses are hashable, which callers may rely on.
        assert len({User.from_json(j) for j in lock_users_json}) == 2
