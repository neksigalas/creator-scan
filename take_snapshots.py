#!/usr/bin/env python3
"""
take_snapshots.py — CreatorScan daily growth snapshot
Run daily via GitHub Actions cron or manual call.
Records today's follower count for every creator in cs_creators.

Usage:
    python take_snapshots.py            # snapshot all creators
    python take_snapshots.py --dry-run  # show what would be snapshotted
"""

import sys
import argparse
import db_cloud as db


def main():
    parser = argparse.ArgumentParser(description="Take daily follower snapshots for all creators")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, do not write to DB")
    args = parser.parse_args()

    print("=== CreatorScan Daily Snapshot ===")

    if args.dry_run:
        print("[DRY RUN] No data will be written.")
        # List creators with followers
        creators = db.get_client().table("cs_creators").select("id, username, platform, followers").execute()
        rows = creators.data or []
        print(f"Would snapshot {len(rows)} creators:")
        for c in rows[:20]:
            print(f"  {c['platform']:12} @{c['username']:30} {c.get('followers',0):,} followers")
        if len(rows) > 20:
            print(f"  … and {len(rows) - 20} more")
        return

    result = db.take_all_snapshots()
    print(f"✅ Snapshots complete: {result['total']} total, {result['written']} new, {result['skipped']} already existed today")
    if result.get("errors"):
        print(f"⚠️  Errors: {result['errors']}")


if __name__ == "__main__":
    main()
