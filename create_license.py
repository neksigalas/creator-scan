#!/usr/bin/env python3
"""
create_license.py — CreatorScan admin CLI for license key management

Usage:
    python create_license.py create --email user@example.com --tier pro
    python create_license.py list
    python create_license.py revoke cs_lic_xxxxxxxxxxxxxxxxxxxxxxxxxxxx

Tiers: starter | pro | agency
"""

import argparse
import sys
import db_cloud as db


def cmd_create(args):
    key = db.create_license_key(email=args.email, tier=args.tier)
    print(f"\n✅ License key created!\n")
    print(f"  Key:   {key}")
    print(f"  Email: {args.email or '(none)'}")
    print(f"  Tier:  {args.tier}\n")
    print(f"Share this key with the customer:")
    print(f"\n  {key}\n")


def cmd_list(args):
    keys = db.list_license_keys()
    if not keys:
        print("No license keys found.")
        return
    print(f"\n{'#':>3}  {'Key':35}  {'Email':30}  {'Tier':10}  {'Active':6}  {'Uses':6}")
    print("─" * 100)
    for i, k in enumerate(keys, 1):
        masked = k["key"][:12] + "…" + k["key"][-4:]
        email  = (k.get("email") or "")[:30]
        tier   = k.get("tier", "starter")
        active = "✓" if k.get("active") else "✗"
        uses   = k.get("usage_count", 0)
        print(f"  {i:>2}  {masked:35}  {email:30}  {tier:10}  {active:6}  {uses:>6}")
    print(f"\nTotal: {len(keys)} keys\n")


def cmd_revoke(args):
    key = args.key
    ok = db.revoke_license_key(key)
    if ok:
        print(f"\n🔴 Revoked: {key}\n")
    else:
        print(f"\n⚠️  Key not found or already revoked: {key}\n")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="CreatorScan license key management")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_create = sub.add_parser("create", help="Create a new license key")
    p_create.add_argument("--email", default=None, help="Customer email")
    p_create.add_argument("--tier", default="starter", choices=["starter", "pro", "agency"], help="License tier")

    sub.add_parser("list", help="List all license keys")

    p_revoke = sub.add_parser("revoke", help="Revoke a license key")
    p_revoke.add_argument("key", help="Full license key to revoke")

    args = parser.parse_args()

    if args.cmd == "create":   cmd_create(args)
    elif args.cmd == "list":   cmd_list(args)
    elif args.cmd == "revoke": cmd_revoke(args)


if __name__ == "__main__":
    main()
