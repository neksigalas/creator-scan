"""
cleanup_emails.py — Null out junk emails in both Supabase and local creators.db

Catches:
  - Placeholder domains  (example.com, domain.com, …)
  - Platform domains     (skool, wix, sentry, youtube, gumroad, …)
  - .gov addresses       (lendermatch@sba.gov, …)
  - Junk local parts     (u003e…, noreply, hex IDs, …)
  - URL fragments        (?body=… Amazon share links)
  - Bare format checks   (must pass RFC-ish regex)

Usage:
    python cleanup_emails.py              # Supabase + local SQLite
    python cleanup_emails.py --cloud-only
    python cleanup_emails.py --local-only
    python cleanup_emails.py --dry-run    # show, don't write
"""

import argparse
import os
import sys
from dotenv import load_dotenv

load_dotenv()

# Reuse the same filter logic as extract_email
from processors.niche import _email_ok

# ── Supabase cleanup ───────────────────────────────────────────────────────────

def _cleaned_email(raw: str):
    """Returns (action, value):
       ('ok',    email)  — already clean and valid
       ('fix',   email)  — trailing junk stripped, now valid → UPDATE
       ('null',  email)  — not salvageable → NULL
    """
    import re as _re
    raw = (raw or "").strip()
    if not raw or raw == "null":
        return ("null", raw)

    # Try the raw value first
    if _email_ok(raw):
        return ("ok", raw)

    # Strip trailing punctuation / backslashes / HTML that got appended
    stripped = _re.sub(r"[\\'\"><\s]+$", "", raw).rstrip(".")
    if stripped and _email_ok(stripped):
        return ("fix", stripped)

    return ("null", raw)


def cleanup_supabase(dry_run: bool) -> int:
    from supabase import create_client
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    if not url or not key:
        print("WARNING: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set — skipping cloud")
        return 0

    client = create_client(url, key)
    nulled = fixed = 0
    offset = 0
    PAGE = 1000

    print("Supabase: scanning...")
    while True:
        result = (client.table("cs_creators")
                  .select("id,display_name,email")
                  .not_.is_("email", "null")
                  .range(offset, offset + PAGE - 1)
                  .execute())
        rows = result.data or []
        if not rows:
            break

        for c in rows:
            action, val = _cleaned_email(c.get("email") or "")
            name = (c.get("display_name") or "")[:40]
            if action == "null":
                print(f"  NULL  {name:40}  {c['email']}")
                if not dry_run:
                    client.table("cs_creators").update(
                        {"email": None, "has_email": 0}
                    ).eq("id", c["id"]).execute()
                nulled += 1
            elif action == "fix":
                print(f"  FIX   {name:40}  {c['email']}  ->  {val}")
                if not dry_run:
                    client.table("cs_creators").update(
                        {"email": val, "has_email": 1}
                    ).eq("id", c["id"]).execute()
                fixed += 1

        if len(rows) < PAGE:
            break
        offset += PAGE

    tag = "[DRY RUN] " if dry_run else ""
    print(f"  -> {tag}nulled {nulled}, fixed {fixed} in Supabase\n")
    return nulled + fixed


# ── SQLite cleanup ─────────────────────────────────────────────────────────────

def cleanup_sqlite(dry_run: bool) -> int:
    import sqlite3
    db_path = "creators.db"
    if not os.path.exists(db_path):
        print(f"ℹ️  {db_path} not found — skipping local")
        return 0

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT id, display_name, email FROM creators WHERE email IS NOT NULL AND email != ''")
    rows = cur.fetchall()
    print(f"SQLite: scanning {len(rows)} creators with email...")

    nulled = fixed = 0
    for row in rows:
        action, val = _cleaned_email(row["email"] or "")
        name = (row["display_name"] or "")[:40]
        if action == "null":
            print(f"  NULL  {name:40}  {row['email']}")
            if not dry_run:
                cur.execute(
                    "UPDATE creators SET email = NULL, has_email = 0 WHERE id = ?",
                    (row["id"],),
                )
            nulled += 1
        elif action == "fix":
            print(f"  FIX   {name:40}  {row['email']}  ->  {val}")
            if not dry_run:
                cur.execute(
                    "UPDATE creators SET email = ?, has_email = 1 WHERE id = ?",
                    (val, row["id"]),
                )
            fixed += 1

    if not dry_run and (nulled + fixed):
        conn.commit()
    conn.close()

    tag = "[DRY RUN] " if dry_run else ""
    print(f"  -> {tag}nulled {nulled}, fixed {fixed} in SQLite\n")
    return nulled + fixed


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Null out junk creator emails")
    parser.add_argument("--dry-run",    action="store_true", help="Show what would be cleared, write nothing")
    parser.add_argument("--cloud-only", action="store_true", help="Only clean Supabase")
    parser.add_argument("--local-only", action="store_true", help="Only clean local SQLite")
    args = parser.parse_args()

    total = 0
    if not args.local_only:
        total += cleanup_supabase(args.dry_run)
    if not args.cloud_only:
        total += cleanup_sqlite(args.dry_run)

    label = "Would clear" if args.dry_run else "Cleared"
    print(f"✅  {label} {total} junk emails total.")


if __name__ == "__main__":
    main()
