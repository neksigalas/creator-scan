"""
Supabase database layer για CreatorScan (production).
Χρησιμοποιεί το supabase-py client — ίδιο interface με db.py.
Tables prefix: cs_ (coexists με dental-case-preflight στο ίδιο project)
"""
import os
import json
import secrets
from datetime import datetime
from typing import Optional

from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

_client: Client | None = None

def get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


# ── Creators ──────────────────────────────────────────────────────────────────

def upsert_creator(data: dict) -> bool:
    """Upsert creator. Επιστρέφει True αν νέος."""
    if isinstance(data.get("niches"), list):
        data["niches"] = json.dumps(data["niches"])
    if isinstance(data.get("tags"), list):
        data["tags"] = json.dumps(data["tags"])

    data["updated_at"] = datetime.utcnow().isoformat()
    client = get_client()

    # Check if exists
    existing = (client.table("cs_creators")
                .select("id")
                .eq("platform", data["platform"])
                .eq("platform_id", data["platform_id"])
                .execute())
    is_new = len(existing.data) == 0

    client.table("cs_creators").upsert(
        data, on_conflict="platform,platform_id"
    ).execute()
    return is_new


def _build_query(table_query, platform=None, niche=None,
                 min_followers=2000, max_followers=100_000,
                 has_email=None, language=None, search=None):
    q = table_query.gte("followers", min_followers).lte("followers", max_followers)
    if platform:    q = q.eq("platform", platform)
    if niche:       q = q.eq("niche", niche)
    if has_email is not None:
        q = q.eq("has_email", 1 if has_email else 0)
    if language:    q = q.ilike("language", language)
    if search:
        # Supabase full-text search on display_name
        q = q.or_(f"display_name.ilike.%{search}%,username.ilike.%{search}%,bio.ilike.%{search}%")
    return q


def query_creators(platform=None, niche=None, min_followers=2000,
                   max_followers=100_000, has_email=None, language=None,
                   search=None, limit=100, offset=0) -> list[dict]:
    client = get_client()
    q = _build_query(
        client.table("cs_creators").select("*"),
        platform, niche, min_followers, max_followers, has_email, language, search
    )
    result = (q.order("followers", desc=True)
               .range(offset, offset + limit - 1)
               .execute())
    return result.data or []


def count_creators(platform=None, niche=None, min_followers=2000,
                   max_followers=100_000, has_email=None, language=None,
                   search=None) -> int:
    client = get_client()
    q = _build_query(
        client.table("cs_creators").select("id", count="exact"),
        platform, niche, min_followers, max_followers, has_email, language, search
    )
    result = q.execute()
    return result.count or 0


def get_stats() -> dict:
    client = get_client()
    total_r   = client.table("cs_creators").select("id", count="exact").execute()
    email_r   = client.table("cs_creators").select("id", count="exact").eq("has_email", 1).execute()
    platform_r = client.table("cs_creators").select("platform").execute()
    niche_r    = client.table("cs_creators").select("niche").execute()

    total      = total_r.count or 0
    with_email = email_r.count or 0

    by_platform: dict[str, int] = {}
    for row in (platform_r.data or []):
        p = row["platform"]
        by_platform[p] = by_platform.get(p, 0) + 1

    niche_counts: dict[str, int] = {}
    for row in (niche_r.data or []):
        n = row["niche"] or "Other"
        niche_counts[n] = niche_counts.get(n, 0) + 1
    by_niche = dict(sorted(niche_counts.items(), key=lambda x: x[1], reverse=True)[:15])

    return {"total": total, "with_email": with_email,
            "by_platform": by_platform, "by_niche": by_niche}


# ── API Keys ──────────────────────────────────────────────────────────────────

TIER_LIMITS = {"free": 100, "pro": 5000, "unlimited": 999_999}

def create_api_key(name: str, tier: str = "free") -> dict:
    key = f"cs_{secrets.token_urlsafe(32)}"
    data = {
        "key": key, "name": name, "tier": tier,
        "limit_per_day": TIER_LIMITS.get(tier, 100),
        "calls_today": 0, "calls_total": 0, "active": True,
        "created_at": datetime.utcnow().isoformat(),
    }
    client = get_client()
    result = client.table("cs_api_keys").insert(data).execute()
    return result.data[0] if result.data else data


def get_api_key(key: str) -> dict | None:
    result = get_client().table("cs_api_keys").select("*").eq("key", key).execute()
    return result.data[0] if result.data else None


def list_api_keys() -> list[dict]:
    result = (get_client().table("cs_api_keys")
              .select("*").order("created_at", desc=True).execute())
    return result.data or []


def revoke_api_key(key: str) -> bool:
    result = (get_client().table("cs_api_keys")
              .update({"active": False}).eq("key", key).execute())
    return bool(result.data)


def check_and_increment(key: str) -> tuple[bool, dict | None]:
    client = get_client()
    result = client.table("cs_api_keys").select("*").eq("key", key).eq("active", True).execute()
    if not result.data:
        return False, None

    info = result.data[0]
    today = datetime.utcnow().strftime("%Y-%m-%d")

    # Reset daily counter on new day
    last = (info.get("last_used_at") or "")[:10]
    if last and last != today:
        client.table("cs_api_keys").update({"calls_today": 0}).eq("key", key).execute()
        info["calls_today"] = 0

    if info["calls_today"] >= info["limit_per_day"]:
        return False, info

    client.table("cs_api_keys").update({
        "calls_today":  info["calls_today"] + 1,
        "calls_total":  info["calls_total"] + 1,
        "last_used_at": datetime.utcnow().isoformat(),
    }).eq("key", key).execute()
    return True, info


def log_api_usage(key: str, endpoint: str, params: str, results: int):
    get_client().table("cs_api_usage").insert({
        "key": key, "endpoint": endpoint,
        "params": params, "results": results,
        "ts": datetime.utcnow().isoformat(),
    }).execute()


def get_key_usage(key: str, days: int = 7) -> list[dict]:
    # Supabase doesn't do GROUP BY easily via REST — return last 100 rows
    result = (get_client().table("cs_api_usage")
              .select("ts,results")
              .eq("key", key)
              .order("ts", desc=True)
              .limit(100)
              .execute())
    return result.data or []


def init_db():
    """No-op for cloud — tables created via SQL migration."""
    pass
