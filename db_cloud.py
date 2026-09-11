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
                 has_email=None, language=None, search=None, min_er=None):
    q = table_query.gte("followers", min_followers).lte("followers", max_followers)
    if platform:    q = q.eq("platform", platform)
    if niche:       q = q.eq("niche", niche)
    if has_email is not None:
        q = q.eq("has_email", 1 if has_email else 0)
    if language:    q = q.ilike("language", language)
    if search:
        q = q.or_(f"display_name.ilike.%{search}%,username.ilike.%{search}%,bio.ilike.%{search}%")
    if min_er is not None:
        q = q.gte("engagement_rate", min_er)
    return q


def query_creators(platform=None, niche=None, min_followers=2000,
                   max_followers=100_000, has_email=None, language=None,
                   search=None, limit=100, offset=0, sort="followers_desc",
                   list_id=None, min_er=None) -> list[dict]:
    client = get_client()

    if list_id is not None:
        list_r = (client.table("cs_list_items")
                  .select("creator_id")
                  .eq("list_id", list_id)
                  .execute())
        ids = [r["creator_id"] for r in (list_r.data or [])]
        if not ids:
            return []
        q = _build_query(
            client.table("cs_creators").select("*").in_("id", ids),
            platform, niche, min_followers, max_followers, has_email, language, search, min_er
        )
    else:
        q = _build_query(
            client.table("cs_creators").select("*"),
            platform, niche, min_followers, max_followers, has_email, language, search, min_er
        )

    # Sort
    if sort == "followers_asc":
        q = q.order("followers", desc=False)
    elif sort == "recent":
        q = q.order("updated_at", desc=True)
    elif sort == "email_first":
        q = q.order("has_email", desc=True).order("followers", desc=True)
    elif sort == "engagement_desc":
        # Supabase doesn't support nullsfirst=False reliably — filter nulls out
        q = q.not_.is_("engagement_rate", "null")
        q = q.order("engagement_rate", desc=True)
    else:  # followers_desc (default)
        q = q.order("followers", desc=True)

    result = (q.range(offset, offset + limit - 1).execute())
    return result.data or []


def get_creator_by_id(creator_id: int) -> dict | None:
    """Επιστρέφει έναν creator με outreach data (για detail page)."""
    client = get_client()
    result = (client.table("cs_creators")
              .select("*")
              .eq("id", creator_id)
              .execute())
    if not result.data:
        return None
    c = result.data[0]
    # Attach outreach
    o_result = (client.table("cs_outreach")
                .select("*")
                .eq("creator_id", creator_id)
                .execute())
    o = o_result.data[0] if o_result.data else {}
    c["outreach_status"] = o.get("status", "new")
    c["outreach_notes"]  = o.get("notes", "")
    return c


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
    total_r    = client.table("cs_creators").select("id", count="exact").execute()
    email_r    = client.table("cs_creators").select("id", count="exact").eq("has_email", 1).execute()
    total      = total_r.count or 0
    with_email = email_r.count or 0

    # Count per platform using individual count queries (avoids 1k row limit)
    by_platform: dict[str, int] = {}
    for p in ["youtube", "twitch", "tiktok", "instagram"]:
        r = client.table("cs_creators").select("id", count="exact").eq("platform", p).execute()
        if r.count:
            by_platform[p] = r.count

    # Niche counts — fetch all with high limit
    niche_r = client.table("cs_creators").select("niche").limit(10000).execute()
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


# ── Outreach CRM ──────────────────────────────────────────────────────────────

def get_outreach_all() -> dict[int, dict]:
    """Επιστρέφει {creator_id: {status, notes}} για όλους."""
    result = get_client().table("cs_outreach").select("*").execute()
    return {r["creator_id"]: r for r in (result.data or [])}


def upsert_outreach(creator_id: int, status: str = None, notes: str = None) -> dict:
    """Upsert outreach record."""
    data: dict = {"creator_id": creator_id, "updated_at": datetime.utcnow().isoformat()}
    if status is not None:
        data["status"] = status
    if notes is not None:
        data["notes"] = notes
    client = get_client()
    result = client.table("cs_outreach").upsert(data, on_conflict="creator_id").execute()
    return result.data[0] if result.data else data


# ── Saved Lists ───────────────────────────────────────────────────────────────

def get_lists() -> list[dict]:
    result = get_client().table("cs_lists").select("*").order("created_at").execute()
    return result.data or []


def create_list(name: str, color: str = "#6366f1") -> dict:
    data = {"name": name, "color": color, "created_at": datetime.utcnow().isoformat()}
    result = get_client().table("cs_lists").insert(data).execute()
    return result.data[0] if result.data else data


def delete_list(list_id: int) -> bool:
    # Delete items first
    get_client().table("cs_list_items").delete().eq("list_id", list_id).execute()
    result = get_client().table("cs_lists").delete().eq("id", list_id).execute()
    return bool(result.data)


def add_to_list(list_id: int, creator_id: int) -> bool:
    data = {"list_id": list_id, "creator_id": creator_id,
            "added_at": datetime.utcnow().isoformat()}
    try:
        get_client().table("cs_list_items").upsert(
            data, on_conflict="list_id,creator_id"
        ).execute()
        return True
    except Exception:
        return False


def remove_from_list(list_id: int, creator_id: int) -> bool:
    result = (get_client().table("cs_list_items")
              .delete()
              .eq("list_id", list_id)
              .eq("creator_id", creator_id)
              .execute())
    return True


def get_list_creator_ids(list_id: int) -> list[int]:
    result = (get_client().table("cs_list_items")
              .select("creator_id")
              .eq("list_id", list_id)
              .execute())
    return [r["creator_id"] for r in (result.data or [])]


def get_list_counts() -> dict[int, int]:
    """Επιστρέφει {list_id: count} για όλες τις λίστες."""
    result = get_client().table("cs_list_items").select("list_id").execute()
    counts: dict[int, int] = {}
    for r in (result.data or []):
        lid = r["list_id"]
        counts[lid] = counts.get(lid, 0) + 1
    return counts
