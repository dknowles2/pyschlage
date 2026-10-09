from datetime import UTC, datetime

from pyschlage.log import LockLog

_DEFAULT_UUID = "ffffffff-ffff-ffff-ffff-ffffffffffff"


class TestFromJson:
    def test_unlocked_by_thumbturn(self, log_json):
        log_json["message"]["eventCode"] = 4
        lock_log = LockLog(
            created_at=datetime(2023, 3, 1, 17, 26, 47, 366000, tzinfo=UTC),
            accessor_id=None,
            access_code_id=None,
            message="Unlocked by thumbturn",
            event_code=4,
        )
        assert LockLog.from_json(log_json) == lock_log

    def test_unlocked_by_keypad(self, log_json):
        log_json["message"].update(
            {
                "eventCode": 2,
                "keypadUuid": "__access-code-id__",
            }
        )
        lock_log = LockLog(
            created_at=datetime(2023, 3, 1, 17, 26, 47, 366000, tzinfo=UTC),
            accessor_id=None,
            access_code_id="__access-code-id__",
            message="Unlocked by keypad",
            event_code=2,
        )
        assert LockLog.from_json(log_json) == lock_log

    def test_unlocked_by_mobile_device(self, log_json):
        log_json["message"].update(
            {
                "eventCode": 7,
                "accessorUuid": "__user-id__",
            }
        )
        lock_log = LockLog(
            created_at=datetime(2023, 3, 1, 17, 26, 47, 366000, tzinfo=UTC),
            accessor_id="__user-id__",
            access_code_id=None,
            message="Unlocked by mobile device",
            event_code=7,
        )
        assert LockLog.from_json(log_json) == lock_log

    def test_unknown_event_code(self, log_json):
        log_json["message"]["eventCode"] = 63
        lock_log = LockLog(
            created_at=datetime(2023, 3, 1, 17, 26, 47, 366000, tzinfo=UTC),
            accessor_id=None,
            access_code_id=None,
            message="Unknown",
            event_code=63,
        )
        assert LockLog.from_json(log_json) == lock_log

    def test_reset_logs(self, log_json):
        log_json["message"] = "RESET_LOGS"
        lock_log = LockLog(
            created_at=datetime(2023, 3, 1, 17, 26, 47, 366000, tzinfo=UTC),
            message="All logs cleared",
            event_code=24,
        )
        assert LockLog.from_json(log_json) == lock_log

    def test_missing_message(self, log_json):
        del log_json["message"]
        lock_log = LockLog(
            created_at=datetime(2023, 3, 1, 17, 26, 47, 366000, tzinfo=UTC),
            message="Unknown",
            event_code=-1,
        )
        assert LockLog.from_json(log_json) == lock_log
