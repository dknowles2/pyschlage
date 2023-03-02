from datetime import datetime

from pyschlage.log import LockLog

_DEFAULT_UUID = "ffffffff-ffff-ffff-ffff-ffffffffffff"


class TestFromJson:
    def test_unlocked_by_thumbturn(self, log_json):
        log_json["message"]["eventCode"] = 4
        lock_log = LockLog(
            created_at=datetime(2023, 3, 1, 17, 26, 47, 366000),
            accessor_id=None,
            access_code_id=None,
            message="Unlocked by thumbturn",
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
            created_at=datetime(2023, 3, 1, 17, 26, 47, 366000),
            accessor_id=None,
            access_code_id="__access-code-id__",
            message="Unlocked by keypad",
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
            created_at=datetime(2023, 3, 1, 17, 26, 47, 366000),
            accessor_id="__user-id__",
            access_code_id=None,
            message="Unlocked by mobile device",
        )
        assert LockLog.from_json(log_json) == lock_log
