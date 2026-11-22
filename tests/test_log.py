from datetime import UTC, datetime

from pyschlage.log import (
    LOG_ACTION_ACTION,
    LOG_ACTION_CLEARED,
    LOG_ACTION_READ,
    UNKNOWN_ACTION,
    LockLog,
)

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
            action=2,
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
            action=2,
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
            action=2,
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
            action=2,
        )
        assert LockLog.from_json(log_json) == lock_log

    def test_reset_logs(self, log_json):
        log_json["message"] = "RESET_LOGS"
        lock_log = LockLog(
            created_at=datetime(2023, 3, 1, 17, 26, 47, 366000, tzinfo=UTC),
            message="All logs cleared",
            event_code=24,
            action=LOG_ACTION_CLEARED,
        )
        assert LockLog.from_json(log_json) == lock_log

    def test_missing_message(self, log_json):
        del log_json["message"]
        lock_log = LockLog(
            created_at=datetime(2023, 3, 1, 17, 26, 47, 366000, tzinfo=UTC),
            message="Unknown",
            event_code=-1,
            action=UNKNOWN_ACTION,
        )
        assert LockLog.from_json(log_json) == lock_log

    def test_passage_mode_activated(self, log_json):
        log_json["message"]["eventCode"] = 48
        lock_log = LockLog(
            created_at=datetime(2023, 3, 1, 17, 26, 47, 366000, tzinfo=UTC),
            accessor_id=None,
            access_code_id=None,
            message="Passage mode activated",
            event_code=48,
            action=2,
        )
        assert LockLog.from_json(log_json) == lock_log

    def test_passage_mode_deactivated(self, log_json):
        log_json["message"]["eventCode"] = 49
        lock_log = LockLog(
            created_at=datetime(2023, 3, 1, 17, 26, 47, 366000, tzinfo=UTC),
            accessor_id=None,
            access_code_id=None,
            message="Passage mode deactivated",
            event_code=49,
            action=2,
        )
        assert LockLog.from_json(log_json) == lock_log

    def test_unlocked_by_key_fob(self, log_json):
        log_json["message"].update(
            {
                "eventCode": 75,
                "action": LOG_ACTION_ACTION,
                "fobId": "__fob-id__",
            }
        )
        lock_log = LockLog(
            created_at=datetime(2023, 3, 1, 17, 26, 47, 366000, tzinfo=UTC),
            message="Unlocked by key fob",
            event_code=75,
            action=LOG_ACTION_ACTION,
            fob_id="__fob-id__",
        )
        assert LockLog.from_json(log_json) == lock_log

    def test_unlocked_by_linked_lock(self, log_json):
        log_json["message"].update(
            {
                "eventCode": 82,
                "action": LOG_ACTION_ACTION,
                "linkedDeviceSn": "__linked-sn__",
            }
        )
        lock_log = LockLog(
            created_at=datetime(2023, 3, 1, 17, 26, 47, 366000, tzinfo=UTC),
            message="Unlocked by linked lock",
            event_code=82,
            action=LOG_ACTION_ACTION,
            linked_device_sn="__linked-sn__",
        )
        assert LockLog.from_json(log_json) == lock_log

    def test_read_action_and_empty_optional_ids(self, log_json):
        log_json["message"].update(
            {
                "eventCode": 4,
                "action": LOG_ACTION_READ,
                "fobId": "",
                "linkedDeviceSn": _DEFAULT_UUID,
            }
        )
        lock_log = LockLog(
            created_at=datetime(2023, 3, 1, 17, 26, 47, 366000, tzinfo=UTC),
            message="Unlocked by thumbturn",
            event_code=4,
            action=LOG_ACTION_READ,
            fob_id=None,
            linked_device_sn=None,
        )
        assert LockLog.from_json(log_json) == lock_log

    def test_missing_action_and_uuids(self, log_json):
        log_json["message"] = {"eventCode": 4}
        lock_log = LockLog(
            created_at=datetime(2023, 3, 1, 17, 26, 47, 366000, tzinfo=UTC),
            message="Unlocked by thumbturn",
            event_code=4,
            action=UNKNOWN_ACTION,
        )
        assert LockLog.from_json(log_json) == lock_log
