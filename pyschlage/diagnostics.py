"""End-to-end diagnostics for Schlage locks.

This module exercises the parts of the Schlage cloud service that pyschlage
depends on and produces a redacted JSON report that can be attached to a
`GitHub issue <https://github.com/dknowles2/pyschlage/issues>`_ to help add
support for a new lock model.

Run it from the command line::

    $ python -m pyschlage.diagnostics

By default the run also *modifies* the lock: it actuates the deadbolt using
both of the transports pyschlage knows about, toggles a few settings and adds
and removes a temporary access code. Pass ``--read-only`` to skip all of that.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from enum import Enum
from functools import partial
from getpass import getpass
import importlib.metadata
import json
import os
import pathlib
import platform
import re
import secrets
import sys
import time
from typing import Any, TextIO

from requests import Response

from .api import Schlage
from .auth import BASE_URL, Auth
from .code import AccessCode
from .device import Device, DeviceType
from .exceptions import Error
from .lock import _WIFI_DEVICE_TYPE_PREFIXES, Lock

REPORT_VERSION = 1
"""Version of the JSON report schema produced by this module."""

DIAGNOSTICS_CODE_NAME = "pyschlage diagnostics"
"""Name given to the temporary access code added by the write checks."""

WRITE_WARNING = """\
*** WARNING: this run will MODIFY your lock ***

It will:
  * lock and unlock the deadbolt a few times, using both of the transports
    pyschlage knows about
  * toggle the beeper, lock-and-leave and auto-lock settings, restoring the
    original values afterwards
  * add a temporary access code named "pyschlage diagnostics", then delete it

Only continue if it is safe to actuate the lock right now, and stay nearby so
you can confirm the lock ends up back in its original state. If any cleanup
step fails, this run will say so loudly at the end -- read that output.

Pass --read-only to collect the report without modifying anything.
"""

_SETTLE_SECONDS = 5
_DEFAULT_ACCESS_CODE_LENGTH = 4
_LOG_LIMIT = 10
_BANNER = "!" * 70

# (setting, Lock attribute, setter, flipped value) for each setting write check.
_SettingProbe = tuple[str, str, Callable[[Any], None], Any]


def _pyschlage_version() -> str:
    try:
        return importlib.metadata.version("pyschlage")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _flip_auto_lock_time(lock: Lock) -> int:
    # Prefer a non-zero delay so the probe doesn't just turn auto-lock off.
    candidates = [t for t in lock._auto_lock_times() if t != lock.auto_lock_time]
    return next((t for t in candidates if t), candidates[0])


def _base_device_type(device_type: str) -> str:
    """Strips the transport suffix, e.g. ``be489wifi2`` -> ``be489``."""
    return re.sub(r"(ble|wifi|wb)\d*$", "", device_type)


def _state_name(is_locked: bool) -> str:
    return "locked" if is_locked else "unlocked"


def _jam_name(is_jammed: bool) -> str:
    return "jammed" if is_jammed else "not jammed"


def _markdown_table(headers: Sequence[str], rows: Iterable[Sequence[str]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return lines


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


class FeatureStatus(str, Enum):
    """Whether a lock supports a pyschlage feature."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNCONFIRMED = "unconfirmed"
    NOT_TESTED = "not tested"


@dataclass
class FeatureSupport:
    """Whether a single pyschlage feature works on a lock."""

    name: str = ""
    """Human readable feature name, e.g. ``"Activity logs"``."""

    status: FeatureStatus = FeatureStatus.NOT_TESTED
    """Whether the feature is supported."""

    notes: str = ""
    """What the run observed."""

    def to_json(self) -> dict[str, Any]:
        """Returns a JSON dict of this FeatureSupport.

        :meta private:
        """
        return {"name": self.name, "status": self.status.value, "notes": self.notes}


@dataclass
class CheckResult:
    """The result of a single diagnostic check."""

    name: str = ""
    """Short identifier for the check, e.g. ``"transport:wifi"``."""

    ok: bool = False
    """Whether the check succeeded."""

    duration_ms: int = 0
    """How long the check took, in milliseconds."""

    detail: str | None = None
    """Human readable description of what the check observed."""

    error: str | None = None
    """The error the check raised, if it failed."""

    data: dict[str, Any] = field(default_factory=dict)
    """Structured data collected by the check."""

    def to_json(self) -> dict[str, Any]:
        """Returns a JSON dict of this CheckResult.

        :meta private:
        """
        return {
            "name": self.name,
            "ok": self.ok,
            "duration_ms": self.duration_ms,
            "detail": self.detail,
            "error": self.error,
            "data": self.data,
        }


@dataclass
class LockDiagnostics:
    """Diagnostics collected for a single lock."""

    device_type: str = ""
    """The ``devicetypeId`` reported by the cloud service."""

    model_name: str = ""
    """The model name reported by the cloud service."""

    known_device_type: bool = False
    """Whether the device type matches a :class:`pyschlage.device.DeviceType`."""

    classified_as_wifi: bool = False
    """Whether pyschlage treats this lock as a WiFi lock."""

    matched_wifi_prefix: str | None = None
    """The WiFi device type prefix that matched, if any."""

    working_transports: list[str] = field(default_factory=list)
    """Names of the lock state transports the cloud service accepted."""

    attributes: dict[str, Any] = field(default_factory=dict)
    """Redacted raw device JSON, as returned by :meth:`Lock.get_diagnostics`."""

    checks: list[CheckResult] = field(default_factory=list)
    """Results of each check run against this lock."""

    features: list[FeatureSupport] = field(default_factory=list)
    """Which pyschlage features the lock supports."""

    suggested_fixes: list[str] = field(default_factory=list)
    """Changes to pyschlage suggested by the collected results."""

    cleanup_failures: list[str] = field(default_factory=list)
    """State this run changed but could not restore."""

    def check(self, name: str) -> CheckResult | None:
        """Returns the result of the named check, or None if it didn't run.

        :meta private:
        """
        return next((c for c in self.checks if c.name == name), None)

    def markdown_fields(self) -> list[tuple[str, str]]:
        """Returns (field, value) pairs describing the lock.

        :meta private:
        """
        refresh = self.check("refresh")
        data = refresh.data if refresh else {}

        def value(key: str) -> str:
            return "unknown" if data.get(key) is None else str(data[key])

        return [
            ("Model name", self.model_name or "unknown"),
            ("Device type", f"`{self.device_type}`"),
            ("Firmware version", value("firmware_version")),
            (
                "Connected",
                "unknown"
                if data.get("connected") is None
                else _yes_no(bool(data["connected"])),
            ),
            ("Battery level", value("battery_level")),
            ("Access code length", value("access_code_length")),
            (
                "Advertised features",
                ", ".join(data.get("advertised_features") or []) or "none",
            ),
            ("Known to pyschlage", _yes_no(self.known_device_type)),
            ("Treated as a WiFi lock", _yes_no(self.classified_as_wifi)),
            ("Matched WiFi device type prefix", self.matched_wifi_prefix or "none"),
            (
                "Working lock state transports",
                ", ".join(self.working_transports) or "none",
            ),
        ]

    def to_json(self) -> dict[str, Any]:
        """Returns a JSON dict of these LockDiagnostics.

        :meta private:
        """
        return {
            "device_type": self.device_type,
            "model_name": self.model_name,
            "known_device_type": self.known_device_type,
            "classified_as_wifi": self.classified_as_wifi,
            "matched_wifi_prefix": self.matched_wifi_prefix,
            "working_transports": self.working_transports,
            "features": [f.to_json() for f in self.features],
            "attributes": self.attributes,
            "checks": [c.to_json() for c in self.checks],
            "suggested_fixes": self.suggested_fixes,
            "cleanup_failures": self.cleanup_failures,
        }


@dataclass
class DiagnosticsReport:
    """A diagnostics report for a Schlage account."""

    report_version: int = REPORT_VERSION
    """Version of the JSON report schema."""

    generated_at: str = ""
    """UTC time at which the report was generated."""

    pyschlage_version: str = ""
    """The installed pyschlage version."""

    python_version: str = ""
    """The Python version used for the run."""

    platform: str = ""
    """The platform the run was performed on."""

    write_checks: bool = False
    """Whether checks that modify the lock were run."""

    account_checks: list[CheckResult] = field(default_factory=list)
    """Results of the account-level checks."""

    devices: list[dict[str, Any]] = field(default_factory=list)
    """Redacted summary of every device attached to the account."""

    locks: list[LockDiagnostics] = field(default_factory=list)
    """Diagnostics for each lock that was checked."""

    requests: list[dict[str, Any]] = field(default_factory=list)
    """Redacted summary of every API request made during the run."""

    @property
    def cleanup_failures(self) -> list[str]:
        """State this run changed but could not restore."""
        return [f for lock in self.locks for f in lock.cleanup_failures]

    @property
    def ok(self) -> bool:
        """Whether the run itself succeeded and all state was restored.

        Individual lock checks are allowed to fail: a failing check is a
        useful result, not a failed run. Notably, exactly one of the two lock
        state transports is expected to fail for any given lock.
        """
        return (
            all(check.ok for check in self.account_checks) and not self.cleanup_failures
        )

    def to_markdown(self) -> str:
        """Returns the report as GitHub flavored Markdown.

        The result is meant to be pasted into a
        `pyschlage issue <https://github.com/dknowles2/pyschlage/issues>`_: it
        holds the feature support table for each lock and the pyschlage
        changes needed for full support. It deliberately leaves out the raw
        device attributes and the request log, which live in the JSON report.

        :rtype: str
        """
        lines = ["## pyschlage lock report", ""]
        lines += _markdown_table(
            ("Field", "Value"),
            [
                ("pyschlage version", f"`{self.pyschlage_version}`"),
                ("Python version", f"`{self.python_version}`"),
                ("Platform", f"`{self.platform}`"),
                ("Generated at", self.generated_at),
                ("Checks that modify the lock", _yes_no(self.write_checks)),
            ],
        )
        for lock in self.locks:
            heading = f"{lock.model_name or 'unknown model'} (`{lock.device_type}`)"
            lines += ["", f"### {heading}", ""]
            lines += _markdown_table(("Field", "Value"), lock.markdown_fields())
            lines += ["", "#### Feature support", ""]
            lines += _markdown_table(
                ("Feature", "Supported", "Notes"),
                [(f.name, f.status.value, f.notes) for f in lock.features],
            )
            if lock.suggested_fixes:
                lines += ["", "#### pyschlage changes needed for full support", ""]
                lines += [f"- {fix}" for fix in lock.suggested_fixes]
            failed = [c for c in lock.checks if not c.ok]
            if failed:
                lines += ["", "#### Failed checks", ""]
                lines += _markdown_table(
                    ("Check", "Error"), [(c.name, f"`{c.error}`") for c in failed]
                )
        failed_account_checks = [c for c in self.account_checks if not c.ok]
        if failed_account_checks:
            lines += ["", "### Failed account checks", ""]
            lines += _markdown_table(
                ("Check", "Error"),
                [(c.name, f"`{c.error}`") for c in failed_account_checks],
            )
        if self.cleanup_failures:
            lines += ["", "### State that could not be restored", ""]
            lines += [f"- {failure}" for failure in self.cleanup_failures]
        lines += [
            "",
            (
                "<!-- The JSON report has the redacted device attributes and "
                "the request log. Please attach it too. -->"
            ),
            "",
        ]
        return "\n".join(lines)

    def to_json(self) -> dict[str, Any]:
        """Returns a JSON dict of this DiagnosticsReport.

        :meta private:
        """
        return {
            "report_version": self.report_version,
            "generated_at": self.generated_at,
            "pyschlage_version": self.pyschlage_version,
            "python_version": self.python_version,
            "platform": self.platform,
            "write_checks": self.write_checks,
            "account_checks": [c.to_json() for c in self.account_checks],
            "devices": self.devices,
            "locks": [lock.to_json() for lock in self.locks],
            "requests": self.requests,
            "cleanup_failures": self.cleanup_failures,
        }


class _RecordingAuth(Auth):
    """Auth wrapper that records the requests made during a diagnostics run.

    :meta private:
    """

    def __init__(self, auth: Auth) -> None:
        # Intentionally does not call super().__init__(): this object delegates
        # everything to the already-constructed |auth|.
        self._wrapped = auth
        self.requests: list[dict[str, Any]] = []

    @property
    def user_id(self) -> str:
        """Returns the unique user id for the authenticated user."""
        return self._wrapped.user_id

    def authenticate(self) -> None:
        """Performs authentication with AWS."""
        self._wrapped.authenticate()

    def request(
        self, method: str, path: str, base_url: str = BASE_URL, **kwargs
    ) -> Response:
        """Performs a request and records it."""
        record: dict[str, Any] = {"method": method.upper(), "path": path}
        self.requests.append(record)
        start = time.monotonic()
        try:
            resp = self._wrapped.request(method, path, base_url=base_url, **kwargs)
        except Exception as ex:
            record["error"] = f"{type(ex).__name__}: {ex}"
            raise
        finally:
            record["duration_ms"] = int((time.monotonic() - start) * 1000)
        record["status"] = resp.status_code
        return resp


class _Collector:
    """Runs the diagnostic checks and collects their results."""

    def __init__(
        self,
        auth: Auth,
        *,
        allow_write: bool = True,
        device_ids: Sequence[str] | None = None,
        out: TextIO | None = None,
    ) -> None:
        self._auth = _RecordingAuth(auth)
        self._schlage = Schlage(self._auth)
        self._allow_write = allow_write
        self._device_ids = set(device_ids) if device_ids else None
        self._out = out if out is not None else sys.stdout
        self._locks: list[Lock] = []
        self._redactions: dict[str, str] = {}
        self._report = DiagnosticsReport(
            generated_at=datetime.now(UTC).isoformat(),
            pyschlage_version=_pyschlage_version(),
            python_version=platform.python_version(),
            platform=platform.platform(),
            write_checks=allow_write,
        )

    # Output helpers.

    def _print(self, line: str = "") -> None:
        print(line, file=self._out)

    def _record(self, results: list[CheckResult], result: CheckResult) -> CheckResult:
        results.append(result)
        status = "ok " if result.ok else "ERR"
        suffix = result.detail if result.ok else result.error
        self._print(f"  {result.name:<30} {status} {suffix or ''}".rstrip())
        return result

    def _check(
        self,
        results: list[CheckResult],
        name: str,
        fn: Callable[[], tuple[str | None, dict[str, Any]]],
    ) -> CheckResult:
        start = time.monotonic()
        try:
            detail, data = fn()
            result = CheckResult(name=name, ok=True, detail=detail, data=data)
        except Exception as ex:  # noqa: BLE001 - any failure is a useful datapoint
            result = CheckResult(
                name=name, ok=False, error=f"{type(ex).__name__}: {ex}"
            )
        result.duration_ms = int((time.monotonic() - start) * 1000)
        return self._record(results, result)

    # Redaction helpers.

    def _redact(self, value: str, placeholder: str) -> None:
        if value:
            self._redactions[value] = placeholder

    def _redact_text(self, text: str) -> str:
        for value, placeholder in self._redactions.items():
            text = text.replace(value, placeholder)
        return text

    # Account checks.

    def _authenticate(self) -> tuple[str | None, dict[str, Any]]:
        self._auth.authenticate()
        self._redact(self._auth.user_id, "<user-id>")
        return "authenticated", {}

    def _check_users(self) -> tuple[str | None, dict[str, Any]]:
        users = self._schlage.users()
        for user in users:
            self._redact(user.user_id, "<user-id>")
        return f"{len(users)} user(s)", {"count": len(users)}

    def _check_devices(self) -> tuple[str | None, dict[str, Any]]:
        resp = self._auth.request("get", Device.request_path())
        device_types = []
        for device_json in resp.json():
            self._redact(device_json.get("deviceId", ""), "<device-id>")
            device_type = device_json.get("devicetypeId", "")
            device_types.append(device_type)
            self._report.devices.append(
                {
                    "devicetypeId": device_type,
                    "modelName": device_json.get("modelName"),
                    "connected": device_json.get("connected"),
                    "role": device_json.get("role"),
                }
            )
        return (
            f"{len(device_types)} device(s): {', '.join(sorted(set(device_types)))}",
            {"count": len(device_types)},
        )

    def _check_locks(self) -> tuple[str | None, dict[str, Any]]:
        locks = self._schlage.locks()
        for lock in locks:
            self._redact(lock.device_id, "<device-id>")
        if self._device_ids is not None:
            locks = [lock for lock in locks if lock.device_id in self._device_ids]
        self._locks = locks
        return f"{len(locks)} lock(s) to check", {"count": len(locks)}

    # Per-lock read checks.

    def _classify(
        self, lock: Lock, diag: LockDiagnostics
    ) -> tuple[str | None, dict[str, Any]]:
        diag.attributes = lock.get_diagnostics()
        diag.known_device_type = any(
            lock.device_type.startswith(dt.value) for dt in DeviceType
        )
        diag.classified_as_wifi = lock._is_wifi_lock()
        diag.matched_wifi_prefix = next(
            (
                p.value
                for p in _WIFI_DEVICE_TYPE_PREFIXES
                if lock.device_type.startswith(p)
            ),
            None,
        )
        detail = (
            f"wifi={diag.classified_as_wifi} "
            f"prefix={diag.matched_wifi_prefix or 'none'} "
            f"known_type={diag.known_device_type}"
        )
        return detail, {}

    def _refresh(self, lock: Lock) -> tuple[str | None, dict[str, Any]]:
        lock.refresh()
        data = {
            "connected": lock.connected,
            "is_locked": lock.is_locked,
            "is_jammed": lock.is_jammed,
            "battery_level": lock.battery_level,
            "firmware_version": lock.firmware_version,
            "auto_lock_time": lock.auto_lock_time,
            "beeper_enabled": lock.beeper_enabled,
            "lock_and_leave_enabled": lock.lock_and_leave_enabled,
            "access_code_length": lock.access_code_length,
            "advertised_features": sorted(
                f.name
                for f in fields(lock.supported_features)
                if getattr(lock.supported_features, f.name)
            ),
            "lock_state_action_type": (
                None
                if lock.lock_state_metadata is None
                else lock.lock_state_metadata.action_type
            ),
        }
        detail = (
            f"connected={lock.connected} locked={lock.is_locked} "
            f"jammed={lock.is_jammed} battery={lock.battery_level}"
        )
        return detail, data

    def _check_logs(self, lock: Lock) -> tuple[str | None, dict[str, Any]]:
        logs = lock.logs(limit=_LOG_LIMIT, sort_desc=True)
        messages = [log.message for log in logs]
        return f"{len(logs)} entry(s)", {"count": len(logs), "messages": messages}

    def _check_access_codes(self, lock: Lock) -> tuple[str | None, dict[str, Any]]:
        codes = lock.get_access_codes()
        summary = [
            {
                "code_length": len(code.code),
                "disabled": code.disabled,
                "notify_on_use": code.notify_on_use,
                "schedule_type": type(code.schedule).__name__
                if code.schedule
                else None,
            }
            for code in codes
        ]
        return f"{len(codes)} code(s)", {"count": len(codes), "codes": summary}

    # Per-lock write checks.

    def _probe_transport(
        self,
        lock: Lock,
        setter: Callable[[Lock, int], None],
        target_locked: bool,
    ) -> tuple[str | None, dict[str, Any]]:
        setter(lock, 1 if target_locked else 0)
        time.sleep(_SETTLE_SECONDS)
        lock.refresh()
        confirmed = lock.is_locked is target_locked
        return (
            f"{_state_name(target_locked)} accepted, confirmed={confirmed}",
            {
                "target_locked": target_locked,
                "confirmed": confirmed,
                "is_locked_after": lock.is_locked,
                "is_jammed_after": lock.is_jammed,
            },
        )

    def _check_transports(self, lock: Lock, diag: LockDiagnostics) -> None:
        if lock.is_locked is None:
            self._record(
                diag.checks,
                CheckResult(
                    name="transports",
                    ok=False,
                    error="lock state is unknown; skipping transport checks",
                ),
            )
            return

        initial = bool(lock.is_locked)
        current = initial
        setters: dict[str, Callable[[Lock, int], None]] = {
            "wifi": Lock._toggle_wifi,
            "bridge": Lock._toggle_bridge,
        }
        for transport, setter in setters.items():
            target = not current
            result = self._check(
                diag.checks,
                f"transport:{transport}",
                partial(self._probe_transport, lock, setter, target),
            )
            if result.ok:
                diag.working_transports.append(transport)
                current = target

        # Each probe refreshes the lock, so this is the observed state rather
        # than the state the probes were asked for.
        if lock.is_locked is initial:
            return

        restore = setters["wifi" if "wifi" in diag.working_transports else "bridge"]
        result = self._check(
            diag.checks,
            "transport:restore",
            partial(self._probe_transport, lock, restore, initial),
        )
        if result.ok and result.data.get("confirmed"):
            return
        if lock.is_locked is None:
            left = "in an unknown state"
        else:
            left = _state_name(lock.is_locked).upper()
        diag.cleanup_failures.append(
            f"the lock may have been left {left}; "
            f"it was {_state_name(initial)} before this run"
        )

    def _probe_setting(
        self, getter: Callable[[], Any], setter: Callable[[Any], None], value: Any
    ) -> tuple[str | None, dict[str, Any]]:
        setter(value)
        actual = getter()
        return (
            f"set to {value!r}, now {actual!r}",
            {"requested": value, "actual": actual},
        )

    def _check_settings(self, lock: Lock, diag: LockDiagnostics) -> None:
        probes: list[_SettingProbe] = [
            ("beeper", "beeper_enabled", lock.set_beeper, not lock.beeper_enabled),
            (
                "lock_and_leave",
                "lock_and_leave_enabled",
                lock.set_lock_and_leave,
                not lock.lock_and_leave_enabled,
            ),
            (
                "auto_lock_time",
                "auto_lock_time",
                lock.set_auto_lock_time,
                _flip_auto_lock_time(lock),
            ),
        ]
        for setting, attr, setter, flipped in probes:
            name = f"setting:{setting}"
            getter: Callable[[], Any] = partial(getattr, lock, attr)
            original = getter()
            result = self._check(
                diag.checks, name, partial(self._probe_setting, getter, setter, flipped)
            )
            if not result.ok:
                continue
            restore = self._check(
                diag.checks,
                f"{name}:restore",
                partial(self._probe_setting, getter, setter, original),
            )
            if not restore.ok or restore.data.get("actual") != original:
                diag.cleanup_failures.append(
                    f"{name} may have been left set to {flipped!r}; "
                    f"it was {original!r} before this run"
                )

    def _add_access_code(
        self, lock: Lock, code: AccessCode
    ) -> tuple[str | None, dict[str, Any]]:
        lock.add_access_code(code)
        self._redact(code.access_code_id or "", "<access-code-id>")
        lock.refresh_access_codes()
        listed = code.access_code_id in (lock.access_codes or {})
        return (
            f"added, id_returned={code.access_code_id is not None} listed={listed}",
            {"id_returned": code.access_code_id is not None, "listed": listed},
        )

    def _delete_access_code(
        self, lock: Lock, code: AccessCode
    ) -> tuple[str | None, dict[str, Any]]:
        code.delete()
        lock.refresh_access_codes()
        remaining = [
            c
            for c in (lock.access_codes or {}).values()
            if c.name == DIAGNOSTICS_CODE_NAME
        ]
        if remaining:
            raise Error(
                f"{len(remaining)} diagnostics code(s) still present after delete"
            )
        return "deleted", {}

    def _check_access_code(self, lock: Lock, diag: LockDiagnostics) -> None:
        length = lock.access_code_length or _DEFAULT_ACCESS_CODE_LENGTH
        code_value = "".join(str(secrets.randbelow(10)) for _ in range(length))
        code = AccessCode(name=DIAGNOSTICS_CODE_NAME, code=code_value)
        added = self._check(
            diag.checks, "access_code:add", partial(self._add_access_code, lock, code)
        )
        if not added.ok:
            return
        deleted = self._check(
            diag.checks,
            "access_code:delete",
            partial(self._delete_access_code, lock, code),
        )
        if not deleted.ok:
            diag.cleanup_failures.append(
                f'the access code named "{DIAGNOSTICS_CODE_NAME}" may have been '
                "left on the lock; delete it using the Schlage app"
            )
            # Deliberately only printed, never written to the report.
            self._print(
                f'  the code digits for "{DIAGNOSTICS_CODE_NAME}" are {code_value}'
            )

    # Feature support.

    def _feature_from_check(
        self,
        diag: LockDiagnostics,
        name: str,
        check_name: str,
        *,
        skipped_by: str | None = None,
    ) -> FeatureSupport:
        check = diag.check(check_name)
        if check is None:
            skipped = diag.check(skipped_by) if skipped_by else None
            notes = "not tested in this run"
            if skipped is not None and skipped.error:
                notes = skipped.error
            return FeatureSupport(
                name=name, status=FeatureStatus.NOT_TESTED, notes=notes
            )
        if not check.ok:
            return FeatureSupport(
                name=name, status=FeatureStatus.UNSUPPORTED, notes=check.error or ""
            )
        status = FeatureStatus.SUPPORTED
        if check.data.get("confirmed") is False:
            status = FeatureStatus.UNCONFIRMED
        return FeatureSupport(name=name, status=status, notes=check.detail or "")

    def _reported_feature(
        self, name: str, value: Any, fmt: Callable[[Any], str] = str
    ) -> FeatureSupport:
        if value is None:
            return FeatureSupport(
                name=name,
                status=FeatureStatus.UNSUPPORTED,
                notes="not reported by the lock",
            )
        return FeatureSupport(
            name=name,
            status=FeatureStatus.SUPPORTED,
            notes=f"reported as {fmt(value)}",
        )

    def _collect_features(self, lock: Lock, diag: LockDiagnostics) -> None:
        diag.features = [
            self._reported_feature("Lock state", lock.is_locked, _state_name),
            self._reported_feature("Jam detection", lock.is_jammed, _jam_name),
            self._reported_feature("Battery level", lock.battery_level),
            self._reported_feature("Firmware version", lock.firmware_version),
            self._feature_from_check(diag, "Activity logs", "logs"),
            self._feature_from_check(diag, "Access code listing", "access_codes"),
            self._feature_from_check(
                diag,
                "Lock/unlock (WiFi attributes)",
                "transport:wifi",
                skipped_by="transports",
            ),
            self._feature_from_check(
                diag,
                "Lock/unlock (bridge command)",
                "transport:bridge",
                skipped_by="transports",
            ),
            self._feature_from_check(diag, "Access code add", "access_code:add"),
            self._feature_from_check(
                diag,
                "Access code delete",
                "access_code:delete",
                skipped_by="access_code:add",
            ),
            self._feature_from_check(diag, "Beeper setting", "setting:beeper"),
            self._feature_from_check(
                diag, "1-touch locking setting", "setting:lock_and_leave"
            ),
            self._feature_from_check(
                diag, "Auto-lock time setting", "setting:auto_lock_time"
            ),
        ]

    # Suggestions.

    def _suggest_fixes(self, lock: Lock, diag: LockDiagnostics) -> None:
        prefix = _base_device_type(lock.device_type)
        if not diag.known_device_type:
            diag.suggested_fixes.append(
                f"add device type {prefix!r} ({lock.device_type!r}) to "
                "pyschlage.device.DeviceType"
            )
        wifi_ok = "wifi" in diag.working_transports
        bridge_ok = "bridge" in diag.working_transports
        if wifi_ok and not bridge_ok and not diag.classified_as_wifi:
            diag.suggested_fixes.append(
                f"treat {prefix!r} as a WiFi lock: add it to "
                "_WIFI_DEVICE_TYPE_PREFIXES in pyschlage/lock.py"
            )
        if bridge_ok and not wifi_ok and diag.classified_as_wifi:
            diag.suggested_fixes.append(
                f"{prefix!r} should not be treated as a WiFi lock: remove it from "
                "_WIFI_DEVICE_TYPE_PREFIXES in pyschlage/lock.py"
            )

    # Driver.

    def _collect_lock(self, lock: Lock, index: int, total: int) -> None:
        diag = LockDiagnostics(device_type=lock.device_type, model_name=lock.model_name)
        self._report.locks.append(diag)
        self._print()
        self._print(
            f"[{index}/{total}] {lock.name} "
            f"({lock.device_type} / {lock.model_name or 'unknown model'})"
        )
        self._check(diag.checks, "classify", partial(self._classify, lock, diag))
        self._check(diag.checks, "refresh", partial(self._refresh, lock))
        self._check(diag.checks, "logs", partial(self._check_logs, lock))
        self._check(
            diag.checks, "access_codes", partial(self._check_access_codes, lock)
        )
        if self._allow_write:
            self._check_transports(lock, diag)
            self._check_settings(lock, diag)
            self._check_access_code(lock, diag)
        self._collect_features(lock, diag)
        self._suggest_fixes(lock, diag)
        for fix in diag.suggested_fixes:
            self._print(f"  suggested fix: {fix}")

    def _finish(self) -> None:
        self._report.requests = [
            {**record, "path": self._redact_text(record["path"])}
            for record in self._auth.requests
        ]
        for diag in self._report.locks:
            diag.checks = [
                CheckResult(
                    name=check.name,
                    ok=check.ok,
                    duration_ms=check.duration_ms,
                    detail=check.detail,
                    error=(
                        None if check.error is None else self._redact_text(check.error)
                    ),
                    data=check.data,
                )
                for check in diag.checks
            ]

        self._print()
        self._print("-" * 70)
        self._print("Copy everything below into a pyschlage issue:")
        self._print("-" * 70)
        self._print()
        self._print(self._report.to_markdown())

        failures = self._report.cleanup_failures
        if not failures:
            self._print("All checks finished and all state was restored.")
            return
        self._print(_BANNER)
        self._print("!!! MANUAL CLEANUP REQUIRED")
        for failure in failures:
            self._print(f"!!!   {failure}")
        self._print("!!! Check the lock and the Schlage app before you walk away.")
        self._print(_BANNER)

    def run(self) -> DiagnosticsReport:
        """Runs all checks and returns the collected report."""
        report = self._report
        self._print(
            f"pyschlage {report.pyschlage_version} diagnostics "
            f"(python {report.python_version}, {report.platform})"
        )
        self._print("write checks: " + ("enabled" if self._allow_write else "disabled"))
        self._print()
        if not self._check(
            report.account_checks, "authenticate", self._authenticate
        ).ok:
            self._print()
            self._print("Authentication failed; aborting.")
            return report
        self._check(report.account_checks, "users", self._check_users)
        self._check(report.account_checks, "devices", self._check_devices)
        self._check(report.account_checks, "locks", self._check_locks)
        for index, lock in enumerate(self._locks, start=1):
            self._collect_lock(lock, index, len(self._locks))
        self._finish()
        return report


def collect(
    auth: Auth,
    *,
    allow_write: bool = True,
    device_ids: Sequence[str] | None = None,
    out: TextIO | None = None,
) -> DiagnosticsReport:
    """Runs diagnostic checks against an account and returns a report.

    Progress is written to ``out`` as the checks run.

    :param auth: Authentication and transport for the API.
    :type auth: pyschlage.Auth
    :param allow_write: Whether to run checks that modify the lock. These
        actuate the deadbolt, toggle settings and add and remove a temporary
        access code.
    :type allow_write: bool
    :param device_ids: If given, only check locks with these device ids.
    :type device_ids: Sequence[str] or None
    :param out: Stream progress is written to. Defaults to ``sys.stdout``.
    :type out: TextIO or None
    :rtype: DiagnosticsReport
    """
    return _Collector(
        auth, allow_write=allow_write, device_ids=device_ids, out=out
    ).run()


def _markdown_path(json_path: str) -> str:
    path = pathlib.Path(json_path)
    if path.suffix == ".json":
        return str(path.with_suffix(".md"))
    return f"{json_path}.md"


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m pyschlage.diagnostics",
        description=(
            "Runs end-to-end diagnostics against a Schlage account and writes a "
            "redacted JSON report that can be attached to a pyschlage issue."
        ),
    )
    parser.add_argument(
        "--username",
        default=os.environ.get("SCHLAGE_USERNAME"),
        help="Schlage username. Defaults to $SCHLAGE_USERNAME, else prompts.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help=(
            "Path the JSON report is written to. The Markdown report is "
            "written next to it. Defaults to a timestamped file."
        ),
    )
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="Skip all checks that modify the lock.",
    )
    parser.add_argument(
        "--lock",
        action="append",
        dest="locks",
        metavar="DEVICE_ID",
        help="Only check this lock. May be repeated.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Don't prompt for confirmation before running write checks.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Runs diagnostics from the command line.

    :param argv: Command line arguments. Defaults to ``sys.argv[1:]``.
    :type argv: Sequence[str] or None
    :rtype: int
    """
    args = _parse_args(argv)
    allow_write = not args.read_only
    if allow_write:
        print(WRITE_WARNING)
        if not args.yes and input('Type "yes" to continue: ').strip().lower() != "yes":
            print("Aborted.")
            return 1

    username = args.username or input("Schlage username: ")
    password = os.environ.get("SCHLAGE_PASSWORD") or getpass("Schlage password: ")

    report = collect(
        Auth(username, password), allow_write=allow_write, device_ids=args.locks
    )

    out = args.out or (f"pyschlage-diagnostics-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json")
    markdown_out = _markdown_path(out)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report.to_json(), f, indent=2, sort_keys=True)
        f.write("\n")
    with open(markdown_out, "w", encoding="utf-8") as f:
        f.write(report.to_markdown())
    print()
    print(f"Wrote {out} and {markdown_out}")
    print(
        "Please review them, then open an issue at "
        "https://github.com/dknowles2/pyschlage/issues with the Markdown as "
        "the description and the JSON attached."
    )
    return 0 if report.ok else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
