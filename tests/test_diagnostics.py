from __future__ import annotations

from copy import deepcopy
import importlib.metadata
import io
import json
from typing import Any
from unittest.mock import Mock, patch

from pytest import MonkeyPatch, fixture

from pyschlage import diagnostics
from pyschlage.exceptions import UnknownError
from pyschlage.lock import Lock


def _resp(json_value: Any) -> Mock:
    return Mock(json=Mock(return_value=json_value), status_code=200)


class FakeService:
    """In-memory stand-in for the Schlage cloud service.

    Instances are used as the ``side_effect`` of a mocked
    :meth:`pyschlage.Auth.request`.
    """

    def __init__(
        self,
        lock_json: dict[str, Any],
        log_json: dict[str, Any],
        access_code_json: dict[str, Any],
        notification_json: dict[str, Any],
    ) -> None:
        self.lock_json = lock_json
        self.log_json = log_json
        self.notification_json = notification_json
        self.access_codes = [access_code_json]
        self.notifications = [notification_json]
        self.device_id = lock_json["deviceId"]
        self.failures: dict[str, tuple[str, int]] = {}
        self.apply_lock_state = True
        self.apply_code_delete = True
        self.dropped_writes: dict[str, int] = {}
        self.time_out_after_apply: set[str] = set()

    def drop_writes(self, key: str, count: int = 1) -> None:
        """Echoes the next |count| writes to |key| without keeping them."""
        self.dropped_writes[key] = count

    def _maybe_time_out(self, key: str) -> None:
        if key in self.time_out_after_apply:
            raise UnknownError("request timed out")

    def fail(self, key: str, message: str = "boom", after: int = 0) -> None:
        """Makes requests matching |key| fail after |after| successful ones."""
        self.failures[key] = (message, after)

    def _maybe_fail(self, key: str) -> None:
        if key not in self.failures:
            return
        message, remaining = self.failures[key]
        if remaining:
            self.failures[key] = (message, remaining - 1)
            return
        raise UnknownError(message)

    def __call__(self, method: str, path: str, **kwargs: Any) -> Mock:
        method = method.lower()
        body: dict[str, Any] = kwargs.get("json") or {}
        device = f"devices/{self.device_id}"
        if method == "get" and path == "users":
            return _resp(self.lock_json["users"])
        if method == "get" and path == "devices":
            return _resp([self.lock_json])
        if method == "get" and path == device:
            return _resp(self.lock_json)
        if method == "put" and path == device:
            return _resp(self._put_attributes(body["attributes"]))
        if method == "post" and path == f"{device}/commands":
            return _resp(self._command(body))
        if method == "get" and path == f"{device}/logs":
            return _resp([self.log_json])
        if method == "get" and path == f"{device}/storage/accesscode":
            return _resp(list(self.access_codes))
        if method == "get" and path == "notifications":
            return _resp(list(self.notifications))
        if method in ("post", "put") and path == "notifications":
            return _resp(self._save_notification(body))
        if method == "delete" and path.startswith("notifications/"):
            notification_id = path.split("/", 1)[1]
            self.notifications = [
                n for n in self.notifications if n["notificationId"] != notification_id
            ]
            return _resp({})
        raise AssertionError(f"unexpected request: {method} {path}")

    def _put_attributes(self, attributes: dict[str, Any]) -> dict[str, Any]:
        for key, value in attributes.items():
            self._maybe_fail(f"put:{key}")
            if key == "lockState" and not self.apply_lock_state:
                continue
            if self.dropped_writes.get(f"put:{key}"):
                self.dropped_writes[f"put:{key}"] -= 1
                echo = deepcopy(self.lock_json)
                echo["attributes"][key] = value
                return echo
            self.lock_json["attributes"][key] = value
            self._maybe_time_out(f"put:{key}")
        return self.lock_json

    def _command(self, body: dict[str, Any]) -> dict[str, Any]:
        name = body["name"]
        data = body["data"]
        self._maybe_fail(f"cmd:{name}")
        if name == "changelockstate":
            if not self.apply_lock_state:
                state = self.lock_json["attributes"]["lockState"]
                return {"result": {"state": state}, "error": None}
            self.lock_json["attributes"]["lockState"] = data["state"]
            return {"result": {"state": data["state"]}, "error": None}
        if name == "addaccesscode":
            access_code_id = "__diag_code_uuid__"
            self.access_codes.append({**data, "accesscodeId": access_code_id})
            self._maybe_time_out(f"cmd:{name}")
            return {"accesscodeId": access_code_id}
        assert name == "deleteaccesscode"
        if self.apply_code_delete:
            self.access_codes = [
                c
                for c in self.access_codes
                if c["accesscodeId"] != data["accesscodeId"]
            ]
        return {}

    def _save_notification(self, body: dict[str, Any]) -> dict[str, Any]:
        notification = {
            **self.notification_json,
            "notificationId": body["notificationId"],
            "notificationDefinitionId": body["notificationDefinitionId"],
            "active": body["active"],
            "filterValue": body.get("filterValue"),
        }
        self.notifications = [
            n
            for n in self.notifications
            if n["notificationId"] != notification["notificationId"]
        ] + [notification]
        return notification


@fixture(autouse=True)
def no_settle(monkeypatch: MonkeyPatch):
    """Keeps the post-actuation settle time out of the test runtime."""
    monkeypatch.setattr(diagnostics, "_SETTLE_SECONDS", 0)


@fixture
def out() -> io.StringIO:
    return io.StringIO()


@fixture
def service(
    mock_auth: Mock,
    lock_json: dict[str, Any],
    log_json: dict[str, Any],
    access_code_json: dict[str, Any],
    notification_json: dict[str, Any],
) -> FakeService:
    svc = FakeService(lock_json, log_json, access_code_json, notification_json)
    mock_auth.request.side_effect = svc
    return svc


def _check(report: diagnostics.DiagnosticsReport, name: str) -> diagnostics.CheckResult:
    for check in report.locks[0].checks:
        if check.name == name:
            return check
    raise AssertionError(f"no such check: {name}")


class TestCollectReadOnly:
    def test_report(
        self, mock_auth: Mock, service: FakeService, out: io.StringIO
    ) -> None:
        report = diagnostics.collect(mock_auth, allow_write=False, out=out)

        assert report.write_checks is False
        assert report.report_version == diagnostics.REPORT_VERSION
        assert [c.name for c in report.account_checks] == [
            "authenticate",
            "users",
            "devices",
            "locks",
        ]
        assert all(c.ok for c in report.account_checks)
        assert report.devices == [
            {
                "devicetypeId": "be489wifi",
                "modelName": "__model_name__",
                "connected": True,
                "role": "owner",
            }
        ]

        diag = report.locks[0]
        assert [c.name for c in diag.checks] == [
            "classify",
            "refresh",
            "logs",
            "access_codes",
        ]
        assert all(c.ok for c in diag.checks)
        assert diag.device_type == "be489wifi"
        assert diag.model_name == "__model_name__"
        assert diag.known_device_type is True
        assert diag.classified_as_wifi is True
        assert diag.matched_wifi_prefix == "be489"
        assert diag.working_transports == []
        assert diag.suggested_fixes == []
        assert diag.cleanup_failures == []
        assert report.ok
        assert "All checks finished" in out.getvalue()

    def test_does_not_write(
        self, mock_auth: Mock, service: FakeService, out: io.StringIO
    ) -> None:
        diagnostics.collect(mock_auth, allow_write=False, out=out)
        methods = {c.args[0] for c in mock_auth.request.call_args_list}
        assert methods == {"get"}

    def test_check_data(
        self, mock_auth: Mock, service: FakeService, out: io.StringIO
    ) -> None:
        report = diagnostics.collect(mock_auth, allow_write=False, out=out)
        assert _check(report, "refresh").data == {
            "connected": True,
            "is_locked": True,
            "is_jammed": False,
            "battery_level": 95,
            "firmware_version": "10.00.00264232",
            "auto_lock_time": 0,
            "beeper_enabled": True,
            "lock_and_leave_enabled": True,
            "access_code_length": 4,
            "advertised_features": [],
            "lock_state_action_type": "periodicDeepQuery",
        }
        assert _check(report, "logs").data == {"count": 1, "messages": ["Unknown"]}
        assert _check(report, "access_codes").data == {
            "count": 1,
            "codes": [
                {
                    "code_length": 4,
                    "disabled": False,
                    "notify_on_use": True,
                    "schedule_type": None,
                }
            ],
        }

    def test_redacts_report(
        self, mock_auth: Mock, service: FakeService, out: io.StringIO
    ) -> None:
        report = diagnostics.collect(mock_auth, allow_write=False, out=out)
        report_json = json.dumps(report.to_json())

        assert "__wifi_uuid__" not in report_json
        assert "user-uuid" not in report_json
        assert "asdf@asdf.com" not in report_json
        assert "AA:BB:CC:00:11:22" not in report_json
        assert "devices/<device-id>" in report_json
        assert report.locks[0].attributes["macAddress"] == "<REDACTED>"
        assert report.locks[0].attributes["modelName"] == "__model_name__"

    def test_advertised_features(
        self,
        mock_auth: Mock,
        service: FakeService,
        lock_json: dict[str, Any],
        out: io.StringIO,
    ) -> None:
        lock_json["attributes"]["supportedFeatures"] = {"vlac": 1, "activityAlarm": 1}
        report = diagnostics.collect(mock_auth, allow_write=False, out=out)

        assert _check(report, "refresh").data["advertised_features"] == [
            "activity_alarm",
            "variable_length_access_codes",
        ]
        assert (
            "| Advertised features | activity_alarm, variable_length_access_codes |"
            in report.to_markdown()
        )

    def test_no_lock_state_metadata(
        self,
        mock_auth: Mock,
        service: FakeService,
        lock_json: dict[str, Any],
        out: io.StringIO,
    ) -> None:
        del lock_json["attributes"]["lockStateMetadata"]
        report = diagnostics.collect(mock_auth, allow_write=False, out=out)
        assert _check(report, "refresh").data["lock_state_action_type"] is None

    def test_lock_filter_by_name(
        self, mock_auth: Mock, service: FakeService, out: io.StringIO
    ) -> None:
        report = diagnostics.collect(
            mock_auth, allow_write=False, locks=["door LOCK"], out=out
        )
        assert [diag.device_type for diag in report.locks] == ["be489wifi"]

    def test_lock_filter_by_device_id(
        self, mock_auth: Mock, service: FakeService, out: io.StringIO
    ) -> None:
        report = diagnostics.collect(
            mock_auth, allow_write=False, locks=["__wifi_uuid__"], out=out
        )
        assert len(report.locks) == 1

    def test_lock_filter_no_match(
        self, mock_auth: Mock, service: FakeService, out: io.StringIO
    ) -> None:
        report = diagnostics.collect(
            mock_auth, allow_write=False, locks=["Back Door"], out=out
        )
        assert report.locks == []
        assert report.account_checks[-1].error == (
            "Error: no lock matches --lock; locks on this account: 'Door Lock'"
        )
        assert not report.ok

    def test_authentication_failure(
        self, mock_auth: Mock, service: FakeService, out: io.StringIO
    ) -> None:
        mock_auth.authenticate.side_effect = UnknownError("nope")
        report = diagnostics.collect(mock_auth, allow_write=False, out=out)

        assert [c.name for c in report.account_checks] == ["authenticate"]
        assert report.account_checks[0].error == "UnknownError: nope"
        assert report.locks == []
        assert not report.ok
        assert "Authentication failed; aborting." in out.getvalue()


class TestCollectWithWrites:
    def test_wifi_lock(
        self,
        mock_auth: Mock,
        service: FakeService,
        lock_json: dict[str, Any],
        out: io.StringIO,
    ) -> None:
        service.fail("cmd:changelockstate", "command not found changelockstate")
        report = diagnostics.collect(mock_auth, out=out)

        diag = report.locks[0]
        assert [c.name for c in diag.checks] == [
            "classify",
            "refresh",
            "logs",
            "access_codes",
            "transport:wifi",
            "transport:bridge",
            "transport:restore",
            "setting:beeper",
            "setting:beeper:restore",
            "setting:lock_and_leave",
            "setting:lock_and_leave:restore",
            "setting:auto_lock_time",
            "setting:auto_lock_time:restore",
            "access_code:add",
            "access_code:delete",
            "access_code:cleanup",
        ]
        assert diag.working_transports == ["wifi"]
        assert _check(report, "transport:wifi").data == {
            "target_locked": False,
            "confirmed": True,
            "is_locked_after": False,
            "is_jammed_after": False,
        }
        assert (
            _check(report, "transport:bridge").error
            == "UnknownError: command not found changelockstate"
        )
        assert _check(report, "access_code:add").data == {
            "id_returned": True,
            "confirmed": True,
        }
        assert diag.suggested_fixes == []
        assert diag.cleanup_failures == []
        assert report.ok

        # All state was restored.
        assert lock_json["attributes"]["lockState"] == 1
        assert lock_json["attributes"]["beeperEnabled"] == 1
        assert lock_json["attributes"]["lockAndLeaveEnabled"] == 1
        assert lock_json["attributes"]["autoLockTime"] == 0
        assert [c["accesscodeId"] for c in service.access_codes] == [
            "__access_code_uuid__"
        ]
        assert "All checks finished" in out.getvalue()

    def test_records_requests(
        self, mock_auth: Mock, service: FakeService, out: io.StringIO
    ) -> None:
        service.fail("cmd:changelockstate", "command not found changelockstate")
        report = diagnostics.collect(mock_auth, out=out)

        commands = [r for r in report.requests if r["path"].endswith("/commands")]
        assert commands[0] == {
            "method": "POST",
            "path": "devices/<device-id>/commands",
            "duration_ms": commands[0]["duration_ms"],
            "error": "UnknownError: command not found changelockstate",
        }
        assert {"method": "GET", "path": "devices"}.items() <= report.requests[
            1
        ].items()
        assert report.requests[1]["status"] == 200

    def test_unknown_device_type(
        self,
        mock_auth: Mock,
        service: FakeService,
        lock_json: dict[str, Any],
        out: io.StringIO,
    ) -> None:
        lock_json["devicetypeId"] = "be999wifi"
        service.fail("cmd:changelockstate", "command not found changelockstate")
        report = diagnostics.collect(mock_auth, out=out)

        diag = report.locks[0]
        assert diag.known_device_type is False
        assert diag.classified_as_wifi is False
        assert diag.matched_wifi_prefix is None
        assert diag.suggested_fixes == [
            "add device type 'be999' ('be999wifi') to pyschlage.device.DeviceType",
            (
                "treat 'be999' as a WiFi lock: add it to "
                "_WIFI_DEVICE_TYPE_PREFIXES in pyschlage/lock.py"
            ),
        ]
        assert "suggested fix: add device type 'be999'" in out.getvalue()

    def test_bridge_only_lock(
        self,
        mock_auth: Mock,
        service: FakeService,
        lock_json: dict[str, Any],
        out: io.StringIO,
    ) -> None:
        service.fail("put:lockState", "not supported")
        report = diagnostics.collect(mock_auth, out=out)

        diag = report.locks[0]
        assert diag.working_transports == ["bridge"]
        assert diag.suggested_fixes == [
            (
                "'be489' should not be treated as a WiFi lock: remove it from "
                "_WIFI_DEVICE_TYPE_PREFIXES in pyschlage/lock.py"
            )
        ]
        assert diag.cleanup_failures == []
        assert lock_json["attributes"]["lockState"] == 1

    def test_lock_state_not_restored(
        self, mock_auth: Mock, service: FakeService, out: io.StringIO
    ) -> None:
        service.fail("put:lockState", "transient error", after=1)
        service.fail("cmd:changelockstate", "command not found changelockstate")
        report = diagnostics.collect(mock_auth, out=out)

        assert report.locks[0].cleanup_failures == [
            "the lock may have been left UNLOCKED; it was locked before this run"
        ]
        assert not report.ok
        output = out.getvalue()
        assert "MANUAL CLEANUP REQUIRED" in output
        assert "the lock may have been left UNLOCKED" in output

    def test_lock_state_not_confirmed(
        self, mock_auth: Mock, service: FakeService, out: io.StringIO
    ) -> None:
        service.apply_lock_state = False
        report = diagnostics.collect(mock_auth, out=out)

        # Both transports were accepted, but the lock never actually moved.
        assert report.locks[0].working_transports == ["wifi", "bridge"]
        assert _check(report, "transport:wifi").data["confirmed"] is False
        # The bridge probe asked for the state the lock was already in, so it
        # reads as confirmed.
        assert _check(report, "transport:bridge").data["confirmed"] is True
        assert report.locks[0].cleanup_failures == []

    def test_restore_leaves_unknown_state(
        self, mock_auth: Mock, out: io.StringIO
    ) -> None:
        lock = Mock(spec=Lock, is_locked=True)
        states = iter([False, None])
        lock.refresh.side_effect = lambda: setattr(lock, "is_locked", next(states))
        lock.send_command.side_effect = UnknownError("command not found")
        diag = diagnostics.LockDiagnostics()

        diagnostics._Collector(mock_auth, out=out)._check_transports(lock, diag)

        assert diag.working_transports == ["wifi"]
        assert diag.cleanup_failures == [
            (
                "the lock may have been left in an unknown state; "
                "it was locked before this run"
            )
        ]

    def test_lock_state_unknown(
        self,
        mock_auth: Mock,
        service: FakeService,
        wifi_lock_unavailable_json: dict[str, Any],
        out: io.StringIO,
    ) -> None:
        report = diagnostics.collect(mock_auth, out=out)

        transports = _check(report, "transports")
        assert transports.ok is False
        assert transports.error == "lock state is unknown; skipping transport checks"
        assert report.locks[0].working_transports == []
        assert _check(report, "access_code:add").ok

    def test_setting_failures(
        self, mock_auth: Mock, service: FakeService, out: io.StringIO
    ) -> None:
        service.fail("cmd:changelockstate", "command not found changelockstate")
        service.fail("put:beeperEnabled", "not restored", after=1)
        service.fail("put:autoLockTime", "not supported")
        report = diagnostics.collect(mock_auth, out=out)

        assert not _check(report, "setting:beeper:restore").ok
        assert not _check(report, "setting:beeper:restore:retry").ok
        assert _check(report, "setting:auto_lock_time").error == (
            "UnknownError: not supported"
        )
        # The rejected write never changed anything, so the restore passes
        # even though its own write is rejected too.
        auto_lock_restore = _check(report, "setting:auto_lock_time:restore")
        assert auto_lock_restore.ok
        assert auto_lock_restore.data["write_error"] == "UnknownError: not supported"
        assert report.locks[0].cleanup_failures == [
            (
                "setting:beeper may have been left set to False; "
                "it was True before this run"
            )
        ]
        assert not report.ok

    def test_setting_restore_echoed_but_not_kept(
        self,
        mock_auth: Mock,
        service: FakeService,
        lock_json: dict[str, Any],
        out: io.StringIO,
    ) -> None:
        # The restore write is echoed back as applied, but the lock keeps the
        # probe's value. The retry has to catch and fix it.
        service.fail("cmd:changelockstate", "command not found changelockstate")
        original_put = service._put_attributes
        writes = []

        def put(attributes: dict[str, Any]) -> dict[str, Any]:
            if "autoLockTime" in attributes:
                writes.append(attributes["autoLockTime"])
                if len(writes) == 2:  # The first restore.
                    service.drop_writes("put:autoLockTime")
            return original_put(attributes)

        service._put_attributes = put  # type: ignore[method-assign]
        report = diagnostics.collect(mock_auth, out=out)

        restore = _check(report, "setting:auto_lock_time:restore")
        assert not restore.ok
        assert restore.error == "Error: wanted 0, lock reports 15"
        assert _check(report, "setting:auto_lock_time:restore:retry").ok
        assert writes == [15, 0, 0]
        assert lock_json["attributes"]["autoLockTime"] == 0
        assert report.locks[0].cleanup_failures == []

    def test_setting_probe_not_kept(
        self, mock_auth: Mock, service: FakeService, out: io.StringIO
    ) -> None:
        service.fail("cmd:changelockstate", "command not found changelockstate")
        service.drop_writes("put:beeperEnabled")
        report = diagnostics.collect(mock_auth, out=out)

        assert _check(report, "setting:beeper").data["confirmed"] is False
        assert (
            _feature(report, "Beeper setting").status
            is diagnostics.FeatureStatus.UNCONFIRMED
        )

    def test_access_code_add_times_out_but_applies(
        self, mock_auth: Mock, service: FakeService, out: io.StringIO
    ) -> None:
        service.fail("cmd:changelockstate", "command not found changelockstate")
        service.time_out_after_apply.add("cmd:addaccesscode")
        report = diagnostics.collect(mock_auth, out=out)

        assert _check(report, "access_code:add").error == (
            "UnknownError: request timed out"
        )
        assert _check(report, "access_code:cleanup").data == {"leftovers_removed": 1}
        assert [c["accesscodeId"] for c in service.access_codes] == [
            "__access_code_uuid__"
        ]
        assert report.locks[0].cleanup_failures == []
        add = _feature(report, "Access code add")
        assert add.status is diagnostics.FeatureStatus.UNCONFIRMED
        assert add.notes == (
            "UnknownError: request timed out; the code was created anyway"
        )

    def test_access_code_add_times_out_without_applying(
        self, mock_auth: Mock, service: FakeService, out: io.StringIO
    ) -> None:
        service.fail("cmd:changelockstate", "command not found changelockstate")
        service.fail("cmd:addaccesscode", "request timed out")
        report = diagnostics.collect(mock_auth, out=out)

        assert _check(report, "access_code:cleanup").data == {"leftovers_removed": 0}
        assert (
            _feature(report, "Access code add").status
            is diagnostics.FeatureStatus.UNCONFIRMED
        )

    def test_access_code_cleanup_cannot_list(
        self, mock_auth: Mock, service: FakeService, out: io.StringIO
    ) -> None:
        service.fail("cmd:changelockstate", "command not found changelockstate")
        service.fail("cmd:addaccesscode", "request timed out")
        original = service.__call__

        def no_listing(method: str, path: str, **kwargs: Any) -> Mock:
            if path.endswith("/storage/accesscode"):
                raise UnknownError("unavailable")
            return original(method, path, **kwargs)

        mock_auth.request.side_effect = no_listing
        report = diagnostics.collect(mock_auth, allow_write=True, out=out)

        assert _check(report, "access_code:cleanup").error == (
            "UnknownError: unavailable"
        )
        assert report.locks[0].cleanup_failures

    def test_transport_times_out_but_applies(
        self,
        mock_auth: Mock,
        service: FakeService,
        lock_json: dict[str, Any],
        out: io.StringIO,
    ) -> None:
        # The WiFi write errors after the lock has already moved, and the
        # bridge path is unsupported. The restore must still happen.
        service.time_out_after_apply.add("put:lockState")
        service.fail("cmd:changelockstate", "command not found changelockstate")
        report = diagnostics.collect(mock_auth, out=out)

        assert not _check(report, "transport:wifi").ok
        assert report.locks[0].working_transports == []
        restore = _check(report, "transport:restore")
        assert restore.data == {
            "confirmed": True,
            "write_error": "UnknownError: request timed out",
        }
        assert lock_json["attributes"]["lockState"] == 1
        assert report.locks[0].cleanup_failures == []

    def test_transport_state_unreadable_after_probes(
        self, mock_auth: Mock, service: FakeService, out: io.StringIO
    ) -> None:
        service.fail("cmd:changelockstate", "command not found changelockstate")
        original = service.__call__
        gets = []

        def flaky_refresh(method: str, path: str, **kwargs: Any) -> Mock:
            if method == "get" and path == f"devices/{service.device_id}":
                gets.append(path)
                if len(gets) >= 3:  # After the probes' own refreshes.
                    raise UnknownError("unavailable")
            return original(method, path, **kwargs)

        mock_auth.request.side_effect = flaky_refresh
        report = diagnostics.collect(mock_auth, out=out)

        assert any("in an unknown state" in f for f in report.locks[0].cleanup_failures)

    def test_access_code_add_failure(
        self, mock_auth: Mock, service: FakeService, out: io.StringIO
    ) -> None:
        service.fail("cmd:changelockstate", "command not found changelockstate")
        service.fail("cmd:addaccesscode", "nope")
        report = diagnostics.collect(mock_auth, out=out)

        names = [c.name for c in report.locks[0].checks]
        assert "access_code:add" in names
        assert "access_code:delete" not in names
        assert report.locks[0].cleanup_failures == []

    def test_access_code_delete_failure(
        self, mock_auth: Mock, service: FakeService, out: io.StringIO
    ) -> None:
        service.fail("cmd:changelockstate", "command not found changelockstate")
        service.fail("cmd:deleteaccesscode", "nope")
        report = diagnostics.collect(mock_auth, out=out)

        assert report.locks[0].cleanup_failures == [
            (
                'the access code named "pyschlage diagnostics" may have been '
                "left on the lock; delete it using the Schlage app"
            )
        ]
        assert "the code digits for" in out.getvalue()
        # The code itself is never written to the report.
        added = next(
            c
            for c in service.access_codes
            if c["friendlyName"] == "pyschlage diagnostics"
        )
        assert str(added["accessCode"]) not in json.dumps(report.to_json())

    def test_access_code_still_present_after_delete(
        self, mock_auth: Mock, service: FakeService, out: io.StringIO
    ) -> None:
        service.fail("cmd:changelockstate", "command not found changelockstate")
        service.apply_code_delete = False
        report = diagnostics.collect(mock_auth, out=out)

        assert _check(report, "access_code:delete").data == {"confirmed": False}
        assert _check(report, "access_code:cleanup").error == (
            "Error: 1 diagnostics code(s) still on the lock"
        )
        assert report.locks[0].cleanup_failures
        assert (
            _feature(report, "Access code delete").status
            is diagnostics.FeatureStatus.UNCONFIRMED
        )


def test_access_code_length_sentinel(
    mock_auth: Mock,
    service: FakeService,
    lock_json: dict[str, Any],
    out: io.StringIO,
) -> None:
    lock_json["attributes"]["accessCodeLength"] = -1
    service.fail("cmd:changelockstate", "command not found changelockstate")
    diagnostics.collect(mock_auth, out=out)

    (added,) = [
        c.kwargs["json"]["data"]
        for c in mock_auth.request.call_args_list
        if (c.kwargs.get("json") or {}).get("name") == "addaccesscode"
    ]
    assert added["accessCodeLength"] == 4


def test_flip_auto_lock_time() -> None:
    sense_pro = Lock(device_type="be889wifi", auto_lock_time=0)
    assert diagnostics._flip_auto_lock_time(sense_pro) == 30
    sense_pro.auto_lock_time = 30
    assert diagnostics._flip_auto_lock_time(sense_pro) == 60
    encode = Lock(device_type="be489wifi", auto_lock_time=15)
    assert diagnostics._flip_auto_lock_time(encode) == 30


def test_base_device_type() -> None:
    assert diagnostics._base_device_type("be489wifi") == "be489"
    assert diagnostics._base_device_type("be489wifi2") == "be489"
    assert diagnostics._base_device_type("be479ble") == "be479"
    assert diagnostics._base_device_type("be889wb") == "be889"
    assert diagnostics._base_device_type("gselent") == "gselent"


class TestMain:
    def test_read_only(
        self, mock_auth: Mock, service: FakeService, tmp_path, monkeypatch: MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SCHLAGE_USERNAME", "user")
        monkeypatch.setenv("SCHLAGE_PASSWORD", "pass")
        out = tmp_path / "report.json"
        with patch.object(diagnostics, "Auth", return_value=mock_auth) as auth_cls:
            assert diagnostics.main(["--read-only", "--out", str(out)]) == 0

        auth_cls.assert_called_once_with("user", "pass")
        report = json.loads(out.read_text())
        assert report["write_checks"] is False
        assert report["cleanup_failures"] == []
        markdown = (tmp_path / "report.md").read_text()
        assert markdown.startswith("## pyschlage lock report\n")
        assert "#### Feature support" in markdown

    def test_default_out_path(
        self, mock_auth: Mock, service: FakeService, tmp_path, monkeypatch: MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SCHLAGE_USERNAME", "user")
        monkeypatch.setenv("SCHLAGE_PASSWORD", "pass")
        monkeypatch.chdir(tmp_path)
        service.fail("cmd:changelockstate", "command not found changelockstate")
        with patch.object(diagnostics, "Auth", return_value=mock_auth):
            assert diagnostics.main(["--yes"]) == 0

        (written,) = list(tmp_path.glob("pyschlage-diagnostics-*.json"))
        assert json.loads(written.read_text())["write_checks"] is True
        (markdown,) = list(tmp_path.glob("pyschlage-diagnostics-*.md"))
        assert "#### Feature support" in markdown.read_text()

    def test_prompts_for_credentials(
        self, mock_auth: Mock, service: FakeService, tmp_path, monkeypatch: MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SCHLAGE_USERNAME", raising=False)
        monkeypatch.delenv("SCHLAGE_PASSWORD", raising=False)
        out = tmp_path / "report.json"
        with (
            patch.object(diagnostics, "Auth", return_value=mock_auth) as auth_cls,
            patch.object(diagnostics, "getpass", return_value="pass") as getpass_fn,
            patch("builtins.input", side_effect=["yes", "user"]) as input_fn,
        ):
            service.fail("cmd:changelockstate", "command not found changelockstate")
            assert diagnostics.main(["--out", str(out)]) == 0

        auth_cls.assert_called_once_with("user", "pass")
        getpass_fn.assert_called_once()
        assert input_fn.call_count == 2

    def test_aborts_without_confirmation(
        self, mock_auth: Mock, tmp_path, capsys
    ) -> None:
        with patch("builtins.input", return_value="no"):
            assert diagnostics.main([]) == 1
        assert "Aborted." in capsys.readouterr().out

    def test_nonzero_on_cleanup_failure(
        self, mock_auth: Mock, service: FakeService, tmp_path, monkeypatch: MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SCHLAGE_USERNAME", "user")
        monkeypatch.setenv("SCHLAGE_PASSWORD", "pass")
        service.fail("put:lockState", "transient error", after=1)
        service.fail("cmd:changelockstate", "command not found changelockstate")
        out = tmp_path / "report.json"
        with patch.object(diagnostics, "Auth", return_value=mock_auth):
            assert diagnostics.main(["--yes", "--out", str(out)]) == 1

        assert json.loads(out.read_text())["cleanup_failures"]

    def test_lock_filter(
        self, mock_auth: Mock, service: FakeService, tmp_path, monkeypatch: MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SCHLAGE_USERNAME", "user")
        monkeypatch.setenv("SCHLAGE_PASSWORD", "pass")
        out = tmp_path / "report.json"
        with patch.object(diagnostics, "Auth", return_value=mock_auth):
            args = ["--read-only", "--lock", "nope", "--out", str(out)]
            assert diagnostics.main(args) == 1

        assert json.loads(out.read_text())["locks"] == []


def test_pyschlage_version_unknown() -> None:
    with patch.object(
        importlib.metadata,
        "version",
        side_effect=importlib.metadata.PackageNotFoundError,
    ):
        assert diagnostics._pyschlage_version() == "unknown"


def test_pyschlage_version() -> None:
    with patch.object(importlib.metadata, "version", return_value="1.2.3"):
        assert diagnostics._pyschlage_version() == "1.2.3"


def _feature(
    report: diagnostics.DiagnosticsReport, name: str
) -> diagnostics.FeatureSupport:
    for feature in report.locks[0].features:
        if feature.name == name:
            return feature
    raise AssertionError(f"no such feature: {name}")


class TestFeatures:
    def test_read_only(
        self, mock_auth: Mock, service: FakeService, out: io.StringIO
    ) -> None:
        report = diagnostics.collect(mock_auth, allow_write=False, out=out)

        assert [(f.name, f.status.value) for f in report.locks[0].features] == [
            ("Lock state", "supported"),
            ("Jam detection", "supported"),
            ("Battery level", "supported"),
            ("Firmware version", "supported"),
            ("Activity logs", "supported"),
            ("Access code listing", "supported"),
            ("Lock/unlock (WiFi attributes)", "not tested"),
            ("Lock/unlock (bridge command)", "not tested"),
            ("Access code add", "not tested"),
            ("Access code delete", "not tested"),
            ("Beeper setting", "not tested"),
            ("1-touch locking setting", "not tested"),
            ("Auto-lock time setting", "not tested"),
        ]
        assert _feature(report, "Lock state").notes == "reported as locked"
        assert _feature(report, "Jam detection").notes == "reported as not jammed"
        assert _feature(report, "Beeper setting").notes == "not tested in this run"

    def test_write(
        self, mock_auth: Mock, service: FakeService, out: io.StringIO
    ) -> None:
        service.fail("cmd:changelockstate", "command not found changelockstate")
        report = diagnostics.collect(mock_auth, out=out)

        wifi = _feature(report, "Lock/unlock (WiFi attributes)")
        assert wifi.status is diagnostics.FeatureStatus.SUPPORTED
        bridge = _feature(report, "Lock/unlock (bridge command)")
        assert bridge.status is diagnostics.FeatureStatus.UNSUPPORTED
        assert bridge.notes == "UnknownError: command not found changelockstate"
        assert (
            _feature(report, "Auto-lock time setting").status
            is diagnostics.FeatureStatus.SUPPORTED
        )

    def test_unconfirmed(
        self, mock_auth: Mock, service: FakeService, out: io.StringIO
    ) -> None:
        service.apply_lock_state = False
        report = diagnostics.collect(mock_auth, out=out)

        assert (
            _feature(report, "Lock/unlock (WiFi attributes)").status
            is diagnostics.FeatureStatus.UNCONFIRMED
        )

    def test_unavailable_lock(
        self,
        mock_auth: Mock,
        service: FakeService,
        wifi_lock_unavailable_json: dict[str, Any],
        out: io.StringIO,
    ) -> None:
        report = diagnostics.collect(mock_auth, out=out)

        assert _feature(report, "Lock state").status is (
            diagnostics.FeatureStatus.UNSUPPORTED
        )
        assert _feature(report, "Battery level").notes == "not reported by the lock"
        transport = _feature(report, "Lock/unlock (bridge command)")
        assert transport.status is diagnostics.FeatureStatus.NOT_TESTED
        assert transport.notes == "lock state is unknown; skipping transport checks"

    def test_access_code_delete_not_tested(
        self, mock_auth: Mock, service: FakeService, out: io.StringIO
    ) -> None:
        service.fail("cmd:changelockstate", "command not found changelockstate")
        service.fail("cmd:addaccesscode", "nope")
        report = diagnostics.collect(mock_auth, out=out)

        delete = _feature(report, "Access code delete")
        assert delete.status is diagnostics.FeatureStatus.NOT_TESTED
        assert delete.notes == "UnknownError: nope"


class TestMarkdown:
    def test_report(
        self,
        mock_auth: Mock,
        service: FakeService,
        lock_json: dict[str, Any],
        out: io.StringIO,
    ) -> None:
        lock_json["devicetypeId"] = "be999wifi"
        lock_json["modelName"] = "BE999WB"
        service.fail("cmd:changelockstate", "command not found changelockstate")
        report = diagnostics.collect(mock_auth, out=out)
        markdown = report.to_markdown()

        assert markdown.startswith("## pyschlage lock report\n")
        assert "| Checks that modify the lock | yes |" in markdown
        assert "### BE999WB (`be999wifi`)" in markdown
        assert "| Device type | `be999wifi` |" in markdown
        assert "| Connected | yes |" in markdown
        assert "| Treated as a WiFi lock | no |" in markdown
        assert "| Working lock state transports | wifi |" in markdown
        assert "#### Feature support" in markdown
        assert "| Feature | Supported | Notes |" in markdown
        assert "| Activity logs | supported | 1 entry(s) |" in markdown
        assert (
            "| Lock/unlock (bridge command) | unsupported | "
            "UnknownError: command not found changelockstate |" in markdown
        )
        assert "#### pyschlage changes needed for full support" in markdown
        assert "- treat 'be999' as a WiFi lock" in markdown
        assert "#### Failed checks" in markdown
        assert "| transport:bridge | `UnknownError: command not found" in markdown
        assert "Please attach it too." in markdown
        # The run prints the same Markdown for users to copy.
        assert markdown in out.getvalue()

    def test_unknown_fields(self) -> None:
        report = diagnostics.DiagnosticsReport(
            locks=[diagnostics.LockDiagnostics(device_type="be999wifi")]
        )
        markdown = report.to_markdown()

        assert "### unknown model (`be999wifi`)" in markdown
        assert "| Model name | unknown |" in markdown
        assert "| Firmware version | unknown |" in markdown
        assert "| Connected | unknown |" in markdown
        assert "| Working lock state transports | none |" in markdown
        assert "| Matched WiFi device type prefix | none |" in markdown

    def test_failed_account_checks_and_cleanup(self) -> None:
        report = diagnostics.DiagnosticsReport(
            account_checks=[
                diagnostics.CheckResult(name="users", ok=False, error="Error: nope")
            ],
            locks=[diagnostics.LockDiagnostics(cleanup_failures=["left UNLOCKED"])],
        )
        markdown = report.to_markdown()

        assert "### Failed account checks" in markdown
        assert "| users | `Error: nope` |" in markdown
        assert "### State that could not be restored" in markdown
        assert "- left UNLOCKED" in markdown


def test_markdown_path() -> None:
    assert diagnostics._markdown_path("report.json") == "report.md"
    assert diagnostics._markdown_path("out/report.json") == "out/report.md"
    assert diagnostics._markdown_path("report.txt") == "report.txt.md"
