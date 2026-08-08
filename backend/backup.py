"""Nightly local backup of app.db + vault.dat into backend/backups/.

Load-bearing, not optional (see CLAUDE.md's "Repo lives inside a
Google-Drive-synced folder" risk note and master-plan Open Risk #1) — Drive's
file-locking can corrupt a live SQLite DB mid-write. This script is a plain
file copy, cheap enough to run every time the scheduler's daily batch runs
(backend/scheduler.py) as well as standalone via Task Scheduler.

Usage: python backend/backup.py [--keep N]
"""

import argparse
import os
import shutil
import sys
from datetime import datetime, timezone

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
BACKUPS_DIR = os.path.join(BACKEND_DIR, "backups")
SOURCES = ["app.db", "vault.dat"]
DEFAULT_KEEP = 14


def run_backup(keep=DEFAULT_KEEP):
    os.makedirs(BACKUPS_DIR, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest_dir = os.path.join(BACKUPS_DIR, stamp)
    copied = []
    for name in SOURCES:
        src = os.path.join(BACKEND_DIR, name)
        if not os.path.exists(src):
            continue  # vault.dat legitimately absent until the vault is set up
        os.makedirs(dest_dir, exist_ok=True)
        shutil.copy2(src, os.path.join(dest_dir, name))
        copied.append(name)

    _prune_old_backups(keep)
    return {"backed_up_at": dest_dir if copied else None, "files": copied}


def _prune_old_backups(keep):
    if not os.path.isdir(BACKUPS_DIR):
        return
    entries = sorted(
        (d for d in os.listdir(BACKUPS_DIR) if os.path.isdir(os.path.join(BACKUPS_DIR, d))),
        reverse=True,
    )
    for stale in entries[keep:]:
        shutil.rmtree(os.path.join(BACKUPS_DIR, stale), ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description="Back up app.db + vault.dat, pruning old snapshots.")
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP, help="How many timestamped backups to retain.")
    args = parser.parse_args()
    result = run_backup(keep=args.keep)
    if result["files"]:
        print(f"Backed up {', '.join(result['files'])} -> {result['backed_up_at']}", file=sys.stderr)
    else:
        print("Nothing to back up yet (no app.db found).", file=sys.stderr)


if __name__ == "__main__":
    main()
