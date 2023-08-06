from __future__ import annotations

from unittest import mock

from pyschlage import api


def test_locks(mock_auth: mock.Mock, lock_json: dict, access_code_json: dict) -> None:
    schlage = api.Schlage(mock_auth)
    mock_auth.request.side_effect = [
        mock.Mock(json=mock.Mock(return_value=[lock_json])),
        mock.Mock(json=mock.Mock(return_value=[access_code_json])),
    ]
    locks = schlage.locks()
    assert len(locks) == 1
    mock_auth.request.assert_has_calls(
        [
            mock.call("get", "devices", params={"archetype": "lock"}),
            mock.call("get", "devices/__wifi_uuid__/storage/accesscode"),
        ]
    )


def test_users(mock_auth: mock.Mock, lock_users_json: list[dict]) -> None:
    schlage = api.Schlage(mock_auth)
    mock_auth.request.return_value = mock.Mock(
        json=mock.Mock(return_value=lock_users_json)
    )

    users = schlage.users()
    assert len(users) == 2
    mock_auth.request.assert_called_once_with("get", "users")
