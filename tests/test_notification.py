from datetime import UTC, datetime
from typing import Any
from unittest.mock import Mock

import pytest

from pyschlage.exceptions import NotAuthenticatedError
from pyschlage.notification import Notification


def test_from_json(mock_auth: Mock, notification_json: dict[str, Any]):
    notification = Notification.from_json(mock_auth, notification_json)
    assert notification.active
    assert notification.created_at == datetime(
        2023, 3, 1, 17, 26, 47, 366000, tzinfo=UTC
    )


def test_save() -> None:
    with pytest.raises(NotAuthenticatedError):
        Notification().save()


def test_delete(mock_auth: Mock, notification: Notification) -> None:
    with pytest.raises(NotAuthenticatedError):
        Notification().delete()

    notification.delete()
    mock_auth.request.assert_called_once_with(
        "delete", "notifications/<user-id>___access_code_uuid__"
    )
    assert notification._auth is None
    assert notification._json == {}
    assert notification.notification_id is None
    assert not notification.active
