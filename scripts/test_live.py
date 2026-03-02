#!/usr/bin/env python3
"""Live integration test script for pyschlage.

Connects to the real Schlage API using your account credentials and exercises
read-only operations against your locks. Lock/unlock can optionally be tested
with an interactive prompt.

Usage:
    SCHLAGE_USERNAME='you@example.com' SCHLAGE_PASSWORD='secret' python scripts/test_live.py

Options (environment variables):
    SCHLAGE_USERNAME   - Your Schlage account email (required)
    SCHLAGE_PASSWORD   - Your Schlage account password (required)
    SCHLAGE_TEST_LOCK  - If set, run lock/unlock test on this lock (interactive)
"""

import os
import sys
import traceback

# Allow running from the repo root without installing the package.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pyschlage.auth import Auth
from pyschlage.api import Schlage


def env_or_die(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        print(f"ERROR: {name} environment variable is required.")
        sys.exit(1)
    return val


def section(title: str):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def test_auth(username: str, password: str) -> Auth:
    section("1. Authentication")
    auth = Auth(username, password)
    print(f"   Authenticating as {username}...")
    auth.authenticate()
    print(f"   SUCCESS - user_id: {auth.user_id}")
    return auth


def test_list_locks(api: Schlage) -> list:
    section("2. Listing Locks")
    locks = api.locks()
    print(f"   Found {len(locks)} lock(s):\n")
    for i, lock in enumerate(locks):
        print(f"   [{i}] {lock.name}")
        print(f"       Device ID   : {lock.device_id}")
        print(f"       Model       : {lock.model_name}")
        print(f"       Connected   : {lock.connected}")
        print(f"       Battery     : {lock.battery_level}%")
        print(f"       Locked      : {lock.is_locked}")
        print(f"       Jammed      : {lock.is_jammed}")
        print(f"       FW version  : {lock.firmware_version}")
        print(f"       Auto-lock   : {lock.auto_lock_time}s")
        print(f"       Beeper      : {lock.beeper_enabled}")
        print(f"       Lock&Leave  : {lock.lock_and_leave_enabled}")
        changed_by = lock.last_changed_by()
        if changed_by:
            print(f"       Changed by  : {changed_by}")
        print()
    return locks


def test_logs(locks: list):
    section("3. Activity Logs")
    for lock in locks:
        print(f"   Lock: {lock.name}")
        logs = lock.logs(limit=10, sort_desc=True)
        if not logs:
            print("       No logs found.")
        for log in logs:
            print(f"       {log.created_at}  {log.message}")
        print()


def test_access_codes(locks: list):
    section("4. Access Codes")
    for lock in locks:
        print(f"   Lock: {lock.name}")
        try:
            codes = lock.get_access_codes()
        except Exception as e:
            print(f"       Could not fetch access codes: {e}")
            continue
        if not codes:
            print("       No access codes found.")
        for code in codes:
            schedule_info = ""
            if code.schedule:
                schedule_info = f" (scheduled)"
            print(
                f"       {code.name}: ****"
                f" [{'disabled' if code.disabled else 'enabled'}]"
                f"{schedule_info}"
                f" notify={code.notify_on_use}"
            )
        print()


def test_users(api: Schlage):
    section("5. Users")
    users = api.users()
    print(f"   Found {len(users)} user(s):\n")
    for user in users:
        print(f"   - {user.name} (id: {user.user_id})")
    print()


def test_diagnostics(locks: list):
    section("6. Diagnostics (redacted)")
    for lock in locks:
        print(f"   Lock: {lock.name}")
        diag = lock.get_diagnostics()
        for key in sorted(diag.keys()):
            val = diag[key]
            if isinstance(val, dict):
                print(f"       {key}:")
                for k2 in sorted(val.keys()):
                    print(f"           {k2}: {val[k2]}")
            else:
                print(f"       {key}: {val}")
        print()


def test_lock_unlock(locks: list):
    section("7. Lock/Unlock Test (interactive)")
    lock_name = os.environ.get("SCHLAGE_TEST_LOCK")
    if not lock_name:
        print("   Skipped. Set SCHLAGE_TEST_LOCK=<lock name> to enable.")
        return

    target = None
    for lock in locks:
        if lock.name.lower() == lock_name.lower() or lock.device_id == lock_name:
            target = lock
            break

    if target is None:
        print(f"   Lock '{lock_name}' not found. Available locks:")
        for lock in locks:
            print(f"       - {lock.name} ({lock.device_id})")
        return

    print(f"   Target lock: {target.name} (currently {'locked' if target.is_locked else 'unlocked'})")
    print()

    if target.is_locked:
        action, reverse = "UNLOCK", "LOCK"
    else:
        action, reverse = "LOCK", "UNLOCK"

    confirm = input(f"   {action} the lock '{target.name}'? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("   Aborted.")
        return

    print(f"   Sending {action} command...")
    if action == "LOCK":
        target.lock()
    else:
        target.unlock()
    print(f"   SUCCESS - lock is now {'locked' if target.is_locked else 'unlocked'}")

    confirm2 = input(f"   {reverse} it back? (yes/no): ").strip().lower()
    if confirm2 == "yes":
        print(f"   Sending {reverse} command...")
        if reverse == "LOCK":
            target.lock()
        else:
            target.unlock()
        print(f"   SUCCESS - lock is now {'locked' if target.is_locked else 'unlocked'}")


def main():
    print("pyschlage Live Integration Test")
    print("================================")

    username = env_or_die("SCHLAGE_USERNAME")
    password = env_or_die("SCHLAGE_PASSWORD")

    passed = 0
    failed = 0
    tests = []

    # Auth
    try:
        auth = test_auth(username, password)
        passed += 1
    except Exception as e:
        print(f"   FAILED: {e}")
        traceback.print_exc()
        print("\nCannot continue without authentication.")
        sys.exit(1)

    api = Schlage(auth)

    # Read-only tests
    tests = [
        ("List locks", lambda: test_list_locks(api)),
        ("Activity logs", lambda: test_logs(main.locks)),
        ("Access codes", lambda: test_access_codes(main.locks)),
        ("Users", lambda: test_users(api)),
        ("Diagnostics", lambda: test_diagnostics(main.locks)),
    ]

    # Get locks first (needed by other tests)
    try:
        main.locks = test_list_locks(api)
        passed += 1
    except Exception as e:
        print(f"   FAILED: {e}")
        traceback.print_exc()
        main.locks = []
        failed += 1

    for name, test_fn in tests[1:]:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            print(f"   FAILED: {e}")
            traceback.print_exc()
            failed += 1

    # Interactive lock/unlock test
    try:
        test_lock_unlock(main.locks)
        passed += 1
    except Exception as e:
        print(f"   FAILED: {e}")
        traceback.print_exc()
        failed += 1

    # Summary
    section("Summary")
    total = passed + failed
    print(f"   {passed}/{total} tests passed")
    if failed:
        print(f"   {failed} test(s) FAILED")
        sys.exit(1)
    else:
        print("   All tests passed!")


if __name__ == "__main__":
    main()
