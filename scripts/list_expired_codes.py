#!/usr/bin/env python3
"""List all expired access codes for each lock on the account.

A code is considered expired if it has a TemporarySchedule whose end time
is in the past.

Usage:
    python scripts/list_expired_codes.py
"""

import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Load .env file from repo root if it exists.
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

from pyschlage.api import Schlage
from pyschlage.auth import Auth
from pyschlage.code import TemporarySchedule

username = os.environ.get("SCHLAGE_USERNAME") or os.environ["schlage_email"]
password = os.environ.get("SCHLAGE_PASSWORD") or os.environ["schlage_password"]

auth = Auth(username, password)
auth.authenticate()
api = Schlage(auth)
locks = api.locks()

now = datetime.now()
total_expired = 0

for lock in locks:
    print(f"\n{'=' * 60}")
    print(f"  {lock.name}")
    print(f"{'=' * 60}")

    codes = lock.get_access_codes()
    expired = [
        c for c in codes
        if isinstance(c.schedule, TemporarySchedule) and c.schedule.end < now
    ]

    if not expired:
        print("  No expired codes.")
        continue

    total_expired += len(expired)
    for code in expired:
        print(
            f"  {code.name:<30s}  "
            f"expired {code.schedule.end.strftime('%Y-%m-%d %I:%M %p')}"
        )

print(f"\n{total_expired} expired code(s) found across {len(locks)} lock(s).")
