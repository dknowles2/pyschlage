from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any
from unittest.mock import Mock, call

import pytest

from pyschlage.exceptions import NotAuthenticatedError, UnknownError
from pyschlage.notification import ON_UNLOCK_ACTION, Notification


def test_from_json(mock_auth: Mock, notification_json: dict[str, Any]):
    notification = Notification.from_json(mock_auth, notification_json)
    assert notification.active
    assert notification.created_at == datetime(
        2023, 3, 1, 17, 26, 47, 366000, tzinfo=UTC
    )


def test_save_unauthenticated() -> None:
    with pytest.raises(NotAuthenticatedError):
        Notification().save()


def test_save_create(mock_auth: Mock, notification_json: dict[str, Any]) -> None:
    notification = Notification(
        _auth=mock_auth,
        notification_id="<user-id>___access_code_uuid__",
        user_id="<user-id>",
        device_id="__wifi_uuid__",
        device_type="be489wifi",
        notification_type=ON_UNLOCK_ACTION,
        active=True,
        filter_value="Access code name",
    )
    mock_auth.request.return_value = Mock(json=Mock(return_value=notification_json))

    notification.save()

    mock_auth.request.assert_called_once_with(
        "post",
        "notifications",
        params={"deviceId": "__wifi_uuid__"},
        json={
            "notificationId": "<user-id>___access_code_uuid__",
            "devicetypeId": "be489wifi",
            "notificationDefinitionId": ON_UNLOCK_ACTION,
            "active": True,
            "filterValue": "Access code name",
        },
    )
    assert notification.created_at == datetime(
        2023, 3, 1, 17, 26, 47, 366000, tzinfo=UTC
    )


def test_save_create_conflict_deletes_and_retries(
    mock_auth: Mock, notification_json: dict[str, Any]
) -> None:
    notification = Notification(
        _auth=mock_auth,
        notification_id="<user-id>___access_code_uuid__",
        user_id="<user-id>",
        device_id="__wifi_uuid__",
        device_type="be489wifi",
        notification_type=ON_UNLOCK_ACTION,
        active=True,
        filter_value="Access code name",
    )
    expected_json = {
        "notificationId": "<user-id>___access_code_uuid__",
        "devicetypeId": "be489wifi",
        "notificationDefinitionId": ON_UNLOCK_ACTION,
        "active": True,
        "filterValue": "Access code name",
    }
    mock_auth.request.side_effect = [
        UnknownError("Conflict", status_code=HTTPStatus.CONFLICT),
        Mock(),
        Mock(json=Mock(return_value=notification_json)),
    ]

    notification.save()

    mock_auth.request.assert_has_calls(
        [
            call(
                "post",
                "notifications",
                params={"deviceId": "__wifi_uuid__"},
                json=expected_json,
            ),
            call("delete", "notifications/<user-id>___access_code_uuid__"),
            call(
                "post",
                "notifications",
                params={"deviceId": "__wifi_uuid__"},
                json=expected_json,
            ),
        ]
    )
    assert notification.active
    assert notification.created_at == datetime(
        2023, 3, 1, 17, 26, 47, 366000, tzinfo=UTC
    )


def test_save_create_conflict_without_id_raises(mock_auth: Mock) -> None:
    notification = Notification(
        _auth=mock_auth,
        device_id="__wifi_uuid__",
        device_type="be489wifi",
        notification_type=ON_UNLOCK_ACTION,
    )
    mock_auth.request.side_effect = UnknownError(
        "Conflict", status_code=HTTPStatus.CONFLICT
    )

    with pytest.raises(UnknownError, match="Conflict"):
        notification.save()

    assert mock_auth.request.call_count == 1


def test_save_create_other_error_raises(mock_auth: Mock) -> None:
    notification = Notification(
        _auth=mock_auth,
        notification_id="<user-id>___access_code_uuid__",
        device_id="__wifi_uuid__",
        device_type="be489wifi",
        notification_type=ON_UNLOCK_ACTION,
    )
    mock_auth.request.side_effect = UnknownError(
        "Internal Server Error", status_code=HTTPStatus.INTERNAL_SERVER_ERROR
    )

    with pytest.raises(UnknownError, match="Internal Server Error"):
        notification.save()

    assert mock_auth.request.call_count == 1


def test_save_create_conflict_retry_error_raises(mock_auth: Mock) -> None:
    notification = Notification(
        _auth=mock_auth,
        notification_id="<user-id>___access_code_uuid__",
        device_id="__wifi_uuid__",
        device_type="be489wifi",
        notification_type=ON_UNLOCK_ACTION,
    )
    mock_auth.request.side_effect = [
        UnknownError("Conflict", status_code=HTTPStatus.CONFLICT),
        Mock(),
        UnknownError("Conflict", status_code=HTTPStatus.CONFLICT),
    ]

    with pytest.raises(UnknownError, match="Conflict"):
        notification.save()

    assert mock_auth.request.call_count == 3


def test_save_update(
    mock_auth: Mock, notification: Notification, notification_json: dict[str, Any]
) -> None:
    notification.device_type = "be489wifi"
    notification.active = False
    notification_json["active"] = False
    mock_auth.request.return_value = Mock(json=Mock(return_value=notification_json))

    notification.save()

    mock_auth.request.assert_called_once_with(
        "put",
        "notifications/<user-id>___access_code_uuid__",
        json={
            "notificationId": "<user-id>___access_code_uuid__",
            "devicetypeId": "be489wifi",
            "notificationDefinitionId": ON_UNLOCK_ACTION,
            "active": False,
            "filterValue": "Access code name",
        },
    )
    assert not notification.active


def test_save_update_not_found_falls_back_to_create(
    mock_auth: Mock, notification: Notification, notification_json: dict[str, Any]
) -> None:
    notification.device_type = "be489wifi"
    notification.active = False
    notification_json["active"] = False
    expected_json = {
        "notificationId": "<user-id>___access_code_uuid__",
        "devicetypeId": "be489wifi",
        "notificationDefinitionId": ON_UNLOCK_ACTION,
        "active": False,
        "filterValue": "Access code name",
    }
    mock_auth.request.side_effect = [
        UnknownError("Not Found", status_code=HTTPStatus.NOT_FOUND),
        Mock(json=Mock(return_value=notification_json)),
    ]

    notification.save()

    mock_auth.request.assert_has_calls(
        [
            call(
                "put",
                "notifications/<user-id>___access_code_uuid__",
                json=expected_json,
            ),
            call(
                "post",
                "notifications",
                params={"deviceId": "__wifi_uuid__"},
                json=expected_json,
            ),
        ]
    )
    assert not notification.active


def test_save_update_not_found_then_conflict_deletes_and_retries(
    mock_auth: Mock, notification: Notification, notification_json: dict[str, Any]
) -> None:
    notification.device_type = "be489wifi"
    expected_json = {
        "notificationId": "<user-id>___access_code_uuid__",
        "devicetypeId": "be489wifi",
        "notificationDefinitionId": ON_UNLOCK_ACTION,
        "active": True,
        "filterValue": "Access code name",
    }
    mock_auth.request.side_effect = [
        UnknownError("Not Found", status_code=HTTPStatus.NOT_FOUND),
        UnknownError("Conflict", status_code=HTTPStatus.CONFLICT),
        Mock(),
        Mock(json=Mock(return_value=notification_json)),
    ]

    notification.save()

    mock_auth.request.assert_has_calls(
        [
            call(
                "put",
                "notifications/<user-id>___access_code_uuid__",
                json=expected_json,
            ),
            call(
                "post",
                "notifications",
                params={"deviceId": "__wifi_uuid__"},
                json=expected_json,
            ),
            call("delete", "notifications/<user-id>___access_code_uuid__"),
            call(
                "post",
                "notifications",
                params={"deviceId": "__wifi_uuid__"},
                json=expected_json,
            ),
        ]
    )
    assert notification.active


def test_save_update_other_error_raises(
    mock_auth: Mock, notification: Notification
) -> None:
    notification.device_type = "be489wifi"
    mock_auth.request.side_effect = UnknownError(
        "Internal Server Error", status_code=HTTPStatus.INTERNAL_SERVER_ERROR
    )

    with pytest.raises(UnknownError, match="Internal Server Error"):
        notification.save()

    assert mock_auth.request.call_count == 1


def test_delete(mock_auth: Mock, notification: Notification) -> None:
    with pytest.raises(NotAuthenticatedError):
        Notification().delete()

    notification.delete()
    mock_auth.request.assert_called_once_with(
        "delete", "notifications/<user-id>___access_code_uuid__"
    )
    assert notification._auth is None
    assert notification._json == {}
    assert notification.notification_id == ""
    assert not notification.active
