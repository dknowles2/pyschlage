#!/usr/bin/env python3
"""Delete all expired access codes for each lock on the account.

A code is considered expired if it has a TemporarySchedule whose end time
is in the past.

Usage:
    python scripts/delete_expired_codes.py          # dry-run (list only)
    python scripts/delete_expired_codes.py --confirm # actually delete
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

dry_run = "--confirm" not in sys.argv

username = os.environ.get("SCHLAGE_USERNAME") or os.environ["schlage_email"]
password = os.environ.get("SCHLAGE_PASSWORD") or os.environ["schlage_password"]

auth = Auth(username, password)
auth.authenticate()
api = Schlage(auth)
locks = api.locks()

now = datetime.now()
total_deleted = 0

if dry_run:
    print("DRY RUN - pass --confirm to actually delete.\n")

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

    for code in expired:
        label = (
            f"  {code.name:<30s}  "
            f"expired {code.schedule.end.strftime('%Y-%m-%d %I:%M %p')}"
        )
        if dry_run:
            print(f"  [WOULD DELETE] {code.name}  "
                  f"expired {code.schedule.end.strftime('%Y-%m-%d %I:%M %p')}")
        else:
            print(f"  Deleting {code.name}...", end=" ", flush=True)
            code.delete()
            print("done.")
            total_deleted += 1

if dry_run:
    print(f"\n{len(expired)} expired code(s) would be deleted. "
          "Run with --confirm to delete.")
else:
    print(f"\n{total_deleted} expired code(s) deleted across {len(locks)} lock(s).")
