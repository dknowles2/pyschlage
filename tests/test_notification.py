from datetime import UTC, datetime
from unittest.mock import Mock

from pyschlage.lock import Lock
from pyschlage.notification import Notification


def test_from_json(mock_auth: Mock, wifi_lock: Lock):
    json = {
        "active": False,
        "createdAt": "2020-04-05T21:53:11.438Z",
        "description": "manages lock/unlock notifications",
        "deviceId": "__device_id__",
        "name": "lock notification",
        "notificationDefinitionId": "onstatelocked",
        "notificationId": "__notification_id__",
        "updatedAt": "2020-04-06T18:19:18.402Z",
        "userId": "eae7b073-de92-4c6c-9b1a-25aa960a36f9",
    }
    notification = Notification.from_json(mock_auth, wifi_lock, json)
    assert not notification.active
    assert notification.created_at == datetime(
        2020, 4, 5, 21, 53, 11, 438000, tzinfo=UTC
    )
