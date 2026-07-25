from datetime import datetime
from typing import Any

from pyschlage.log import LockLog


class TestLockLog:
    def test_request_path(self) -> None:
        assert LockLog.request_path("__device_uuid__") == "devices/__device_uuid__/logs"

    def test_from_json_unknown_event(self, log_json: dict[str, Any]) -> None:
        assert LockLog.from_json(log_json) == LockLog(
            created_at=datetime.fromisoformat("2023-03-01T17:26:47.366Z"),
            message="Unknown",
            accessor_id=None,
            access_code_id=None,
        )

    def test_from_json_known_event(self, log_json: dict[str, Any]) -> None:
        log_json["message"]["eventCode"] = 1
        assert LockLog.from_json(log_json).message == "Locked by keypad"

    def test_from_json_keeps_non_default_uuids(self, log_json: dict[str, Any]) -> None:
        log_json["message"]["accessorUuid"] = "user-uuid"
        log_json["message"]["keypadUuid"] = "code-uuid"
        log = LockLog.from_json(log_json)
        assert log.accessor_id == "user-uuid"
        assert log.access_code_id == "code-uuid"
