"""Helper utilities for the Schlage MCP server."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyschlage.api import Schlage
    from pyschlage.code import AccessCode, RecurringSchedule, TemporarySchedule
    from pyschlage.lock import Lock
    from pyschlage.log import LockLog
    from pyschlage.user import User


def load_env() -> None:
    """Load .env file from the repo root if it exists."""
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


def resolve_lock(api: Schlage, identifier: str) -> Lock:
    """Find a lock by name (case-insensitive) or device_id.

    Raises ValueError with a list of available locks if not found.
    """
    locks = api.locks()
    for lock in locks:
        if lock.name.lower() == identifier.lower() or lock.device_id == identifier:
            return lock
    available = ", ".join(f"{l.name} ({l.device_id})" for l in locks)
    raise ValueError(f"Lock '{identifier}' not found. Available locks: {available}")


def serialize_lock(lock: Lock) -> dict:
    """Serialize a Lock to a plain dict."""
    return {
        "name": lock.name,
        "device_id": lock.device_id,
        "model_name": lock.model_name,
        "connected": lock.connected,
        "battery_level": lock.battery_level,
        "is_locked": lock.is_locked,
        "is_jammed": lock.is_jammed,
        "beeper_enabled": lock.beeper_enabled,
        "lock_and_leave_enabled": lock.lock_and_leave_enabled,
        "auto_lock_time": lock.auto_lock_time,
        "firmware_version": lock.firmware_version,
    }


def serialize_access_code(code: AccessCode) -> dict:
    """Serialize an AccessCode to a plain dict with masked PIN."""
    from pyschlage.code import RecurringSchedule, TemporarySchedule

    masked_pin = f"**{code.code[-2:]}" if len(code.code) >= 2 else "****"

    schedule_info: dict | None = None
    if isinstance(code.schedule, TemporarySchedule):
        schedule_info = {
            "type": "temporary",
            "start": code.schedule.start.isoformat(),
            "end": code.schedule.end.isoformat(),
        }
    elif isinstance(code.schedule, RecurringSchedule):
        dow = code.schedule.days_of_week
        schedule_info = {
            "type": "recurring",
            "days_of_week": {
                "sun": dow.sun,
                "mon": dow.mon,
                "tue": dow.tue,
                "wed": dow.wed,
                "thu": dow.thu,
                "fri": dow.fri,
                "sat": dow.sat,
            },
            "start_time": f"{code.schedule.start_hour:02d}:{code.schedule.start_minute:02d}",
            "end_time": f"{code.schedule.end_hour:02d}:{code.schedule.end_minute:02d}",
        }

    return {
        "name": code.name,
        "access_code_id": code.access_code_id,
        "masked_pin": masked_pin,
        "disabled": code.disabled,
        "notify_on_use": code.notify_on_use,
        "schedule": schedule_info,
    }


def serialize_log(log: LockLog) -> dict:
    """Serialize a LockLog to a plain dict."""
    return {
        "created_at": log.created_at.isoformat(),
        "message": log.message,
        "accessor_id": log.accessor_id,
        "access_code_id": log.access_code_id,
    }


def serialize_user(user: User) -> dict:
    """Serialize a User to a plain dict."""
    return {
        "user_id": user.user_id,
        "name": user.name,
        "email": user.email,
    }
