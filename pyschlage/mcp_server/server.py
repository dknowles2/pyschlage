"""MCP server for Schlage lock management."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from mcp.server.fastmcp import Context, FastMCP

from pyschlage.api import Schlage
from pyschlage.auth import Auth
from pyschlage.code import (
    AccessCode,
    DaysOfWeek,
    RecurringSchedule,
    TemporarySchedule,
)
from pyschlage.lock import AUTO_LOCK_TIMES

from .helpers import (
    load_env,
    resolve_lock,
    serialize_access_code,
    serialize_lock,
    serialize_log,
    serialize_user,
)


@asynccontextmanager
async def _lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
    """Authenticate once at startup and share the API instance."""
    load_env()
    username = os.environ.get("SCHLAGE_USERNAME") or os.environ.get("schlage_email")
    password = os.environ.get("SCHLAGE_PASSWORD") or os.environ.get("schlage_password")
    if not username or not password:
        raise RuntimeError(
            "Set SCHLAGE_USERNAME/SCHLAGE_PASSWORD (or schlage_email/schlage_password) "
            "in environment or .env file."
        )
    auth = Auth(username, password)
    auth.authenticate()
    api = Schlage(auth)
    yield {"api": api}


mcp = FastMCP("schlage", lifespan=_lifespan)


def _json(obj: Any) -> str:
    return json.dumps(obj, indent=2)


def _error(msg: str) -> str:
    return _json({"error": msg})


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def list_locks(ctx: Context) -> str:
    """List all Schlage locks on the account with current status."""
    try:
        api: Schlage = ctx.request_context.lifespan_context["api"]
        locks = api.locks()
        return _json([serialize_lock(lock) for lock in locks])
    except Exception as e:
        return _error(str(e))


@mcp.tool()
def get_lock_status(ctx: Context, lock: str) -> str:
    """Get detailed status of a specific lock including last_changed_by and keypad state.

    Args:
        lock: Lock name (case-insensitive) or device_id.
    """
    try:
        api: Schlage = ctx.request_context.lifespan_context["api"]
        target = resolve_lock(api, lock)
        target.refresh()
        info = serialize_lock(target)
        info["last_changed_by"] = target.last_changed_by()
        info["keypad_disabled"] = target.keypad_disabled()
        return _json(info)
    except Exception as e:
        return _error(str(e))


@mcp.tool()
def get_lock_diagnostics(ctx: Context, lock: str) -> str:
    """Get hardware diagnostics for a lock (firmware, WiFi, battery details).

    Args:
        lock: Lock name (case-insensitive) or device_id.
    """
    try:
        api: Schlage = ctx.request_context.lifespan_context["api"]
        target = resolve_lock(api, lock)
        return _json(target.get_diagnostics())
    except Exception as e:
        return _error(str(e))


@mcp.tool()
def lock_door(ctx: Context, lock: str, confirm: bool = False) -> str:
    """Physically lock a door. Requires confirm=True.

    Args:
        lock: Lock name (case-insensitive) or device_id.
        confirm: Must be True to execute. Safety check to prevent accidental locking.
    """
    if not confirm:
        return _error("Safety check: set confirm=True to lock the door.")
    try:
        api: Schlage = ctx.request_context.lifespan_context["api"]
        target = resolve_lock(api, lock)
        target.lock()
        return _json({"status": "locked", "lock": target.name})
    except Exception as e:
        return _error(str(e))


@mcp.tool()
def unlock_door(ctx: Context, lock: str, confirm: bool = False) -> str:
    """Physically unlock a door. HIGH RISK - requires confirm=True.

    This grants physical access. Only use when the user has explicitly
    asked to unlock and confirmed the action.

    Args:
        lock: Lock name (case-insensitive) or device_id.
        confirm: Must be True to execute. Safety check to prevent accidental unlocking.
    """
    if not confirm:
        return _error(
            "Safety check: set confirm=True to unlock the door. "
            "This is a HIGH RISK action that grants physical access."
        )
    try:
        api: Schlage = ctx.request_context.lifespan_context["api"]
        target = resolve_lock(api, lock)
        target.unlock()
        return _json({"status": "unlocked", "lock": target.name})
    except Exception as e:
        return _error(str(e))


@mcp.tool()
def set_beeper(ctx: Context, lock: str, enabled: bool) -> str:
    """Toggle the keypress beep on a lock.

    Args:
        lock: Lock name (case-insensitive) or device_id.
        enabled: True to enable the beeper, False to disable.
    """
    try:
        api: Schlage = ctx.request_context.lifespan_context["api"]
        target = resolve_lock(api, lock)
        target.set_beeper(enabled)
        return _json({"beeper_enabled": enabled, "lock": target.name})
    except Exception as e:
        return _error(str(e))


@mcp.tool()
def set_lock_and_leave(ctx: Context, lock: str, enabled: bool) -> str:
    """Toggle 1-Touch Locking (lock-and-leave) on a lock.

    Args:
        lock: Lock name (case-insensitive) or device_id.
        enabled: True to enable, False to disable.
    """
    try:
        api: Schlage = ctx.request_context.lifespan_context["api"]
        target = resolve_lock(api, lock)
        target.set_lock_and_leave(enabled)
        return _json({"lock_and_leave_enabled": enabled, "lock": target.name})
    except Exception as e:
        return _error(str(e))


@mcp.tool()
def set_auto_lock_time(ctx: Context, lock: str, seconds: int) -> str:
    """Set the auto-lock timer on a lock. Use 0 to disable.

    Args:
        lock: Lock name (case-insensitive) or device_id.
        seconds: Auto-lock time in seconds. Valid values: 0, 5, 15, 30, 60, 120, 240, 300, 360, 600.
    """
    if seconds not in AUTO_LOCK_TIMES:
        return _error(f"Invalid auto_lock_time. Must be one of: {list(AUTO_LOCK_TIMES)}")
    try:
        api: Schlage = ctx.request_context.lifespan_context["api"]
        target = resolve_lock(api, lock)
        target.set_auto_lock_time(seconds)
        return _json({"auto_lock_time": seconds, "lock": target.name})
    except Exception as e:
        return _error(str(e))


@mcp.tool()
def get_lock_logs(
    ctx: Context,
    lock: str,
    limit: int = 20,
    newest_first: bool = True,
) -> str:
    """Get activity logs for a lock.

    Args:
        lock: Lock name (case-insensitive) or device_id.
        limit: Maximum number of log entries to return (default 20).
        newest_first: Sort newest first (default True).
    """
    try:
        api: Schlage = ctx.request_context.lifespan_context["api"]
        target = resolve_lock(api, lock)
        logs = target.logs(limit=limit, sort_desc=newest_first)
        return _json([serialize_log(log) for log in logs])
    except Exception as e:
        return _error(str(e))


@mcp.tool()
def list_access_codes(ctx: Context, lock: str) -> str:
    """List all access codes for a lock (PINs are masked).

    Args:
        lock: Lock name (case-insensitive) or device_id.
    """
    try:
        api: Schlage = ctx.request_context.lifespan_context["api"]
        target = resolve_lock(api, lock)
        codes = target.get_access_codes()
        return _json([serialize_access_code(c) for c in codes])
    except Exception as e:
        return _error(str(e))


@mcp.tool()
def add_access_code(
    ctx: Context,
    lock: str,
    name: str,
    code: str,
    notify_on_use: bool = False,
    schedule_type: str | None = None,
    start_datetime: str | None = None,
    end_datetime: str | None = None,
    days_of_week: dict[str, bool] | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    timezone: str = "America/New_York",
) -> str:
    """Create a new access code on a lock.

    Args:
        lock: Lock name (case-insensitive) or device_id.
        name: Friendly name for the code (e.g. "Dog Walker").
        code: PIN code as a string of digits (typically 4-8 digits).
        notify_on_use: Send push notification when code is used.
        schedule_type: null for always-active, "temporary" for date range, "recurring" for weekly.
        start_datetime: ISO 8601 datetime for temporary schedule start (in the specified timezone).
        end_datetime: ISO 8601 datetime for temporary schedule end (in the specified timezone).
        days_of_week: Dict of day bools for recurring schedule, e.g. {"mon": true, "fri": true}.
        start_time: Start time "HH:MM" for recurring schedule.
        end_time: End time "HH:MM" for recurring schedule.
        timezone: IANA timezone for interpreting start/end datetimes (default "America/New_York").
    """
    try:
        api: Schlage = ctx.request_context.lifespan_context["api"]
        target = resolve_lock(api, lock)
        tz = ZoneInfo(timezone)

        schedule = _build_schedule(
            schedule_type, start_datetime, end_datetime,
            days_of_week, start_time, end_time, tz=tz,
        )

        access_code = AccessCode(
            name=name,
            code=code,
            schedule=schedule,
            notify_on_use=notify_on_use,
        )
        target.add_access_code(access_code)
        return _json({
            "created": True,
            "access_code_id": access_code.access_code_id,
            "name": name,
            "lock": target.name,
        })
    except Exception as e:
        return _error(str(e))


@mcp.tool()
def update_access_code(
    ctx: Context,
    lock: str,
    access_code_id: str,
    name: str | None = None,
    code: str | None = None,
    notify_on_use: bool | None = None,
    disabled: bool | None = None,
    schedule_type: str | None = None,
    start_datetime: str | None = None,
    end_datetime: str | None = None,
    days_of_week: dict[str, bool] | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    timezone: str = "America/New_York",
) -> str:
    """Update an existing access code.

    Args:
        lock: Lock name (case-insensitive) or device_id.
        access_code_id: The ID of the access code to update.
        name: New friendly name (optional).
        code: New PIN code (optional).
        notify_on_use: Update push notification setting (optional).
        disabled: Set disabled state (optional).
        schedule_type: Change schedule type (optional). Use null, "temporary", or "recurring".
        start_datetime: ISO 8601 datetime for temporary schedule start (in the specified timezone).
        end_datetime: ISO 8601 datetime for temporary schedule end (in the specified timezone).
        days_of_week: Dict of day bools for recurring schedule.
        start_time: Start time "HH:MM" for recurring schedule.
        end_time: End time "HH:MM" for recurring schedule.
        timezone: IANA timezone for interpreting start/end datetimes (default "America/New_York").
    """
    try:
        api: Schlage = ctx.request_context.lifespan_context["api"]
        target = resolve_lock(api, lock)
        tz = ZoneInfo(timezone)
        codes = target.get_access_codes()
        match = None
        for c in codes:
            if c.access_code_id == access_code_id:
                match = c
                break
        if match is None:
            return _error(
                f"Access code '{access_code_id}' not found on lock '{target.name}'."
            )

        if name is not None:
            match.name = name
        if code is not None:
            match.code = code
        if notify_on_use is not None:
            match.notify_on_use = notify_on_use
        if disabled is not None:
            match.disabled = disabled
        if schedule_type is not None:
            match.schedule = _build_schedule(
                schedule_type, start_datetime, end_datetime,
                days_of_week, start_time, end_time, tz=tz,
            )

        match.save()
        return _json({
            "updated": True,
            "access_code_id": match.access_code_id,
            "lock": target.name,
        })
    except Exception as e:
        return _error(str(e))


@mcp.tool()
def delete_access_code(
    ctx: Context,
    lock: str,
    access_code_id: str,
    confirm: bool = False,
) -> str:
    """Permanently delete an access code. Requires confirm=True.

    Args:
        lock: Lock name (case-insensitive) or device_id.
        access_code_id: The ID of the access code to delete.
        confirm: Must be True to execute. This action is irreversible.
    """
    if not confirm:
        return _error("Safety check: set confirm=True to permanently delete this access code.")
    try:
        api: Schlage = ctx.request_context.lifespan_context["api"]
        target = resolve_lock(api, lock)
        codes = target.get_access_codes()
        match = None
        for c in codes:
            if c.access_code_id == access_code_id:
                match = c
                break
        if match is None:
            return _error(
                f"Access code '{access_code_id}' not found on lock '{target.name}'."
            )
        code_name = match.name
        match.delete()
        return _json({
            "deleted": True,
            "name": code_name,
            "access_code_id": access_code_id,
            "lock": target.name,
        })
    except Exception as e:
        return _error(str(e))


@mcp.tool()
def delete_expired_codes(
    ctx: Context,
    lock: str,
    confirm: bool = False,
    dry_run: bool = True,
) -> str:
    """Clean up expired temporary access codes. Defaults to dry_run=True.

    Args:
        lock: Lock name (case-insensitive) or device_id.
        confirm: Must be True to execute deletions (even in dry_run mode for safety).
        dry_run: If True (default), only lists expired codes without deleting. Set to False to actually delete.
    """
    if not confirm:
        return _error("Safety check: set confirm=True. Use dry_run=True first to preview.")
    try:
        api: Schlage = ctx.request_context.lifespan_context["api"]
        target = resolve_lock(api, lock)
        codes = target.get_access_codes()
        now = datetime.now()
        expired = [
            c for c in codes
            if isinstance(c.schedule, TemporarySchedule) and c.schedule.end < now
        ]

        if not expired:
            return _json({"message": "No expired codes found.", "lock": target.name})

        results = []
        for c in expired:
            entry = {
                "name": c.name,
                "access_code_id": c.access_code_id,
                "expired_at": c.schedule.end.isoformat(),
            }
            if dry_run:
                entry["action"] = "would_delete"
            else:
                c.delete()
                entry["action"] = "deleted"
            results.append(entry)

        return _json({
            "lock": target.name,
            "dry_run": dry_run,
            "expired_codes": results,
            "count": len(results),
        })
    except Exception as e:
        return _error(str(e))


@mcp.tool()
def list_users(ctx: Context) -> str:
    """List all users associated with the Schlage account."""
    try:
        api: Schlage = ctx.request_context.lifespan_context["api"]
        users = api.users()
        return _json([serialize_user(u) for u in users])
    except Exception as e:
        return _error(str(e))


# ---------------------------------------------------------------------------
# Schedule builder helper
# ---------------------------------------------------------------------------


def _local_to_utc_naive(dt_str: str, tz: ZoneInfo) -> datetime:
    """Parse an ISO 8601 string as local time and return a naive datetime that
    produces the correct Schlage epoch when .timestamp() is called.

    Empirically confirmed: the Schlage API stores epoch seconds and the mobile
    app displays the UTC interpretation as the wall-clock time (no timezone
    conversion). To make the app show the intended local time, we send an epoch
    where the UTC wall-clock matches the desired display time.

    Example (EDT, UTC-4): input "16:00" (4pm ET) → subtract 4h offset → send
    naive 12:00 → .timestamp() converts 12pm EDT → 4pm UTC epoch → app shows
    4pm. Verified: preview screen shows correct time; detail screen shows +1h
    due to a known Schlage app DST display bug.

    Steps:
      1. Interpret input as wall-clock time in the given timezone.
      2. Replace tzinfo with UTC (wall-clock components become the UTC target).
      3. Convert to naive system-local so .timestamp() round-trips correctly.
    """
    dt = datetime.fromisoformat(dt_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    else:
        # Explicit offset provided — convert to target tz to get wall-clock time
        dt = dt.astimezone(tz)
    # Treat the local wall-clock as UTC (what Schlage will display)
    wall_as_utc = dt.replace(tzinfo=timezone.utc)
    # Convert to naive system-local so .timestamp() reverses this exactly
    return datetime.fromtimestamp(wall_as_utc.timestamp())


def _build_schedule(
    schedule_type: str | None,
    start_datetime: str | None,
    end_datetime: str | None,
    days_of_week: dict[str, bool] | None,
    start_time: str | None,
    end_time: str | None,
    tz: ZoneInfo | None = None,
) -> TemporarySchedule | RecurringSchedule | None:
    """Build a schedule object from tool parameters."""
    if schedule_type is None:
        return None

    if schedule_type == "temporary":
        if not start_datetime or not end_datetime:
            raise ValueError("Temporary schedule requires start_datetime and end_datetime.")
        local_tz = tz or ZoneInfo("America/New_York")
        return TemporarySchedule(
            start=_local_to_utc_naive(start_datetime, local_tz),
            end=_local_to_utc_naive(end_datetime, local_tz),
        )

    if schedule_type == "recurring":
        dow = DaysOfWeek()
        if days_of_week:
            dow = DaysOfWeek(
                sun=days_of_week.get("sun", False),
                mon=days_of_week.get("mon", False),
                tue=days_of_week.get("tue", False),
                wed=days_of_week.get("wed", False),
                thu=days_of_week.get("thu", False),
                fri=days_of_week.get("fri", False),
                sat=days_of_week.get("sat", False),
            )
        start_h, start_m = 0, 0
        end_h, end_m = 23, 59
        if start_time:
            parts = start_time.split(":")
            start_h, start_m = int(parts[0]), int(parts[1])
        if end_time:
            parts = end_time.split(":")
            end_h, end_m = int(parts[0]), int(parts[1])
        return RecurringSchedule(
            days_of_week=dow,
            start_hour=start_h,
            start_minute=start_m,
            end_hour=end_h,
            end_minute=end_m,
        )

    raise ValueError(f"Invalid schedule_type '{schedule_type}'. Use 'temporary' or 'recurring'.")


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------

_AGENT_GUIDE = """\
# Schlage Lock Management Guide

## Getting Started
1. Call `list_locks` first to see all locks and their current status.
2. Reference locks by their **name** (case-insensitive) or **device_id**.
3. Use `get_lock_status` for detailed info on a specific lock.

## Safety Rules
- **Never unlock a door** without explicit user confirmation. The `unlock_door`
  tool requires `confirm=True` and you should always ask the user before calling it.
- **lock_door** also requires `confirm=True` as a safety measure.
- **delete_access_code** is irreversible - always confirm with the user.
- **delete_expired_codes** defaults to `dry_run=True`. Always preview first,
  then set `dry_run=False` only after the user approves the list.

## Lock Status Interpretation
- `is_locked`: True = deadbolt extended (locked), False = retracted (unlocked), null = unavailable
- `is_jammed`: True = motor couldn't fully extend/retract the bolt
- `connected`: True = lock is online and reachable via WiFi
- `battery_level`: Percentage (100=full). Warn user below 20%. Critical below 10%.
- `keypad_disabled`: True = too many wrong PIN attempts, temporary lockout

## Access Code Best Practices
- Use descriptive names: "Dog Walker - Sarah", "Airbnb Guest Oct 2024"
- **Temporary codes** have start/end datetimes - ideal for guests with specific visits
- **Recurring codes** have day-of-week + time windows - ideal for regular service workers
- Codes with no schedule are **always active** - use for permanent household members
- Run `delete_expired_codes` periodically to clean up old temporary codes
- **Timezone:** `add_access_code` and `update_access_code` accept a `timezone` parameter
  (default: "America/New_York"). Pass datetimes as local wall-clock times in that timezone,
  e.g. `start_datetime: "2026-03-15T16:00:00"` with `timezone: "America/New_York"` means 4pm ET.

## Log Message Types
Common messages and what they mean:
- "Locked by keypad" / "Unlocked by keypad" - Someone used a PIN code
- "Locked by thumbturn" / "Unlocked by thumbturn" - Physical turn from inside
- "Locked by mobile device" / "Unlocked by mobile device" - App or API control
- "Locked by Schlage button" - 1-Touch Locking (lock-and-leave)
- "Lock jammed" - Bolt couldn't fully extend/retract
- "Keypad disabled invalid code" - Too many wrong attempts
- "Locked by time" - Auto-lock timer engaged

## Diagnostics Interpretation
- `wifiRssi`: WiFi signal strength in dBm
  - Above -50: Excellent
  - -50 to -65: Good
  - -65 to -75: Fair (may see occasional disconnects)
  - Below -75: Poor (consider a WiFi extender)
- `batteryLevel`: See battery notes above
- `mainFirmwareVersion`: Current lock firmware
- `bleFirmwareVersion`: Bluetooth firmware
- `wifiFirmwareVersion`: WiFi module firmware
"""


@mcp.resource("schlage://guide")
def agent_guide() -> str:
    """Comprehensive guide for AI agents managing Schlage locks."""
    return _AGENT_GUIDE


@mcp.resource("schlage://locks")
def all_locks_resource(ctx: Context) -> str:
    """Current status of all locks (dynamic)."""
    api: Schlage = ctx.request_context.lifespan_context["api"]
    locks = api.locks()
    return _json([serialize_lock(lock) for lock in locks])


@mcp.resource("schlage://locks/{lock_id}/codes")
def lock_codes_resource(ctx: Context, lock_id: str) -> str:
    """Access codes for a specific lock (dynamic)."""
    api: Schlage = ctx.request_context.lifespan_context["api"]
    target = resolve_lock(api, lock_id)
    codes = target.get_access_codes()
    return _json([serialize_access_code(c) for c in codes])


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
