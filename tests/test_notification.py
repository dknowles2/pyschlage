from datetime import datetime
from typing import Any

from pyschlage.notification import ON_UNLOCK_ACTION, Notification


class TestNotification:
    def test_request_path(self) -> None:
        assert Notification.request_path() == "notifications"
        assert Notification.request_path("abc") == "notifications/abc"

    def test_id_for_access_code(self) -> None:
        assert Notification.id_for_access_code("user", "code") == "user_code"

    def test_from_json(self, notification_json: dict[str, Any]) -> None:
        assert Notification.from_json(notification_json) == Notification(
            notification_id="<user-id>___access_code_uuid__",
            user_id="<user-id>",
            device_id="__wifi_uuid__",
            notification_type=ON_UNLOCK_ACTION,
            active=True,
            filter_value="Access code name",
            created_at=datetime.fromisoformat("2023-03-01T17:26:47.366Z"),
            updated_at=datetime.fromisoformat("2023-03-01T17:26:47.366Z"),
        )

    def test_from_json_no_filter_value(self, notification_json: dict[str, Any]) -> None:
        del notification_json["filterValue"]
        assert Notification.from_json(notification_json).filter_value is None

    def test_to_json(self, notification: Notification) -> None:
        assert notification.to_json() == {
            "notificationId": "<user-id>___access_code_uuid__",
            "devicetypeId": None,
            "notificationDefinitionId": ON_UNLOCK_ACTION,
            "active": True,
            "filterValue": "Access code name",
        }

    def test_to_json_omits_unset_filter_value(self) -> None:
        assert "filterValue" not in Notification(notification_id="abc").to_json()

    def test_raw_json_excluded_from_equality(
        self, notification_json: dict[str, Any]
    ) -> None:
        one = Notification.from_json(notification_json)
        two = Notification.from_json({**notification_json, "extra": "field"})
        assert one == two
