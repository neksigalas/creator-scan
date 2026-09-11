"""
Sync local SQLite → Supabase cloud DB.

Διαβάζει όλους τους creators από το local creators.db
και τους ανεβάζει στο Supabase cs_creators table.

Usage: python sync_local_to_cloud.py [--dry-run]
"""
import sys
import time
import dotenv

dotenv.load_dotenv()

import db           # local SQLite
import db_cloud     # Supabase

DRY_RUN = "--dry-run" in sys.argv
BATCH = 50          # upsert in batches

def get_all_local() -> list[dict]:
    """Reads ALL creators from local SQLite."""
    import sqlite3
    conn = sqlite3.connect("creators.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM creators")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def local_to_cloud_dict(r: dict) -> dict:
    """Map local SQLite row → cloud creator dict."""
    return {
        "platform":        r.get("platform") or "",
        "platform_id":     r.get("platform_id") or "",
        "username":        r.get("username") or "",
        "display_name":    r.get("display_name") or r.get("username") or "",
        "followers":       int(r.get("followers") or 0),
        "avg_views":       r.get("avg_views"),
        "engagement_rate": r.get("engagement_rate"),
        "niche":           r.get("niche") or "Other",
        "language":        r.get("language"),
        "country":         r.get("country"),
        "bio":             (r.get("bio") or "")[:1000],
        "profile_url":     r.get("profile_url") or "",
        "avatar_url":      r.get("avatar_url") or "",
        "email":           r.get("email"),
        "has_email":       1 if r.get("email") else 0,
        "tags":            [],
    }

print("=== Local SQLite -> Supabase Sync ===")
if DRY_RUN:
    print("DRY RUN — nothing will be written")

db.init_db()
local_rows = get_all_local()
print(f"Local creators: {len(local_rows)}")

before = db_cloud.get_stats()
print(f"Supabase before: {before.get('total', '?')} creators")
print()

new_count = 0
updated_count = 0
errors = 0

for i, row in enumerate(local_rows):
    if i % 100 == 0:
        print(f"  Progress: {i}/{len(local_rows)} ({new_count} new, {errors} errors)...")

    creator = local_to_cloud_dict(row)
    if not creator["platform"] or not creator["username"]:
        continue

    if DRY_RUN:
        new_count += 1
        continue

    try:
        is_new = db_cloud.upsert_creator(creator)
        if is_new:
            new_count += 1
        else:
            updated_count += 1
    except Exception as e:
        errors += 1
        if errors <= 5:
            print(f"  Error on @{creator['username']}: {e}")

    # Small pause every 50 to avoid rate limiting
    if (i + 1) % 50 == 0:
        time.sleep(0.5)

print()
after = db_cloud.get_stats()
print(f"=== Done ===")
print(f"Processed: {len(local_rows)} local creators")
print(f"New: {new_count} | Updated: {updated_count} | Errors: {errors}")
print(f"Supabase after: {after.get('total', '?')} creators")
print(f"With email: {after.get('with_email', '?')}")
