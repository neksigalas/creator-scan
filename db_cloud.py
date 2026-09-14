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


# ── License Keys (paywall) ───────────────────────────────────────────────────

def create_license_key(email: str, tier: str = "starter") -> dict:
    """Create a new license key (admin only)."""
    key = f"cs_lic_{secrets.token_urlsafe(24)}"
    data = {
        "key": key, "email": email, "tier": tier,
        "active": True,
        "created_at": datetime.utcnow().isoformat(),
        "usage_count": 0,
    }
    client = get_client()
    result = client.table("cs_license_keys").insert(data).execute()
    return result.data[0] if result.data else data


def validate_license_key(key: str) -> dict | None:
    """Validate a license key. Returns key info or None if invalid."""
    if not key or not key.startswith("cs_lic_"):
        return None
    client = get_client()
    result = (client.table("cs_license_keys")
              .select("*")
              .eq("key", key)
              .eq("active", True)
              .execute())
    if not result.data:
        return None
    info = result.data[0]
    # Check expiry
    if info.get("expires_at"):
        from datetime import timezone
        exp = datetime.fromisoformat(info["expires_at"].replace("Z", "+00:00"))
        if exp < datetime.now(tz=timezone.utc):
            return None
    # Update usage
    client.table("cs_license_keys").update({
        "last_used_at": datetime.utcnow().isoformat(),
        "usage_count": (info.get("usage_count") or 0) + 1,
    }).eq("key", key).execute()
    return info


def list_license_keys() -> list[dict]:
    result = (get_client().table("cs_license_keys")
              .select("*").order("created_at", desc=True).execute())
    return result.data or []


def revoke_license_key(key: str) -> bool:
    result = (get_client().table("cs_license_keys")
              .update({"active": False}).eq("key", key).execute())
    return bool(result.data)


# ── Authenticity Score ────────────────────────────────────────────────────────

_NICHE_AVG_ER: dict[str, float] = {
    "Gaming": 3.5, "Tech": 2.8, "Fitness": 5.5, "Beauty": 4.5,
    "Food": 4.2, "Travel": 3.0, "Finance": 2.5, "Education": 3.8,
    "Music": 4.0, "Art & Design": 6.0, "Fashion": 3.5, "Comedy": 5.0,
    "Lifestyle": 4.0, "Parenting": 5.2, "DIY & Crafts": 5.8,
    "Sports": 4.5, "Pets & Animals": 6.2, "Business": 2.8,
}
_DEFAULT_AVG_ER = 3.5


def compute_auth_score(creator: dict) -> int:
    """
    Compute authenticity score 0-100.
    Higher = more likely to be a real engaged creator.
    Low scores may indicate fake/purchased followers.
    """
    score = 50

    followers  = creator.get("followers") or 0
    avg_views  = creator.get("avg_views") or 0
    er         = creator.get("engagement_rate")
    bio        = creator.get("bio") or ""
    email      = creator.get("email") or ""
    platform   = creator.get("platform") or ""
    niche      = creator.get("niche") or ""

    # ── ER check (most important signal) ─────────────────
    niche_avg = _NICHE_AVG_ER.get(niche, _DEFAULT_AVG_ER)
    if er is not None:
        if er >= niche_avg * 1.8:
            score += 22   # well above average → very engaged
        elif er >= niche_avg:
            score += 14   # above average
        elif er >= niche_avg * 0.5:
            score += 5    # somewhat below average
        elif er >= niche_avg * 0.2:
            score -= 15   # well below average
        else:
            score -= 28   # very low → suspicious

    # ── View-to-follower ratio (YouTube / TikTok) ─────────
    if platform in ("youtube", "tiktok") and avg_views and followers:
        vtr = avg_views / followers
        if vtr >= 0.12:
            score += 12
        elif vtr >= 0.04:
            score += 5
        elif vtr < 0.01:
            score -= 12

    # ── Bio completeness ──────────────────────────────────
    blen = len(bio.strip())
    if blen >= 100:
        score += 12
    elif blen >= 30:
        score += 6

    # ── Email presence ────────────────────────────────────
    if email:
        score += 8

    # ── Platform reliability bonus ────────────────────────
    if platform in ("youtube", "twitch"):
        score += 4   # these APIs return accurate follower counts

    return max(0, min(100, score))


def backfill_auth_scores(batch_size: int = 200) -> int:
    """Compute and store auth_score for all creators missing one.
    Always fetches from offset=0 since updated rows leave the IS NULL result set."""
    client = get_client()
    updated = 0
    while True:
        result = (client.table("cs_creators")
                  .select("*")
                  .is_("auth_score", "null")
                  .limit(batch_size)
                  .execute())
        rows = result.data or []
        if not rows:
            break
        for row in rows:
            score = compute_auth_score(row)
            client.table("cs_creators").update({"auth_score": score}).eq("id", row["id"]).execute()
            updated += 1
    return updated


# ── Growth Tracking (follower snapshots) ─────────────────────────────────────

def take_snapshot(creator_id: int, followers: int) -> bool:
    """Save today's follower count for a creator. No-op if already saved today."""
    from datetime import date
    client = get_client()
    today = date.today().isoformat()
    try:
        client.table("cs_creator_snapshots").upsert(
            {"creator_id": creator_id, "followers": followers, "date": today},
            on_conflict="creator_id,date"
        ).execute()
        return True
    except Exception:
        return False


def get_creator_snapshots(creator_id: int, days: int = 30) -> list[dict]:
    """Return follower history for the last N days."""
    client = get_client()
    result = (client.table("cs_creator_snapshots")
              .select("date,followers")
              .eq("creator_id", creator_id)
              .order("date", desc=False)
              .limit(days)
              .execute())
    return result.data or []


def take_all_snapshots() -> dict:
    """Snapshot today's follower count for all creators. Called by daily cron.
    Returns dict with total, written, skipped, errors counts."""
    client = get_client()
    total = written = skipped = errors = 0
    offset = 0
    while True:
        result = (client.table("cs_creators")
                  .select("id,followers")
                  .limit(500)
                  .offset(offset)
                  .execute())
        rows = result.data or []
        if not rows:
            break
        for row in rows:
            total += 1
            if row.get("followers"):
                try:
                    ok = take_snapshot(row["id"], row["followers"])
                    if ok:
                        written += 1
                    else:
                        skipped += 1
                except Exception:
                    errors += 1
            else:
                skipped += 1
        offset += 500
    return {"total": total, "written": written, "skipped": skipped, "errors": errors}


# ── Creator Join Requests ─────────────────────────────────────────────────────

def submit_join_request(data: dict) -> dict:
    """Save a self-registration request."""
    row = {
        "platform":      data.get("platform", ""),
        "username":      data.get("username", ""),
        "profile_url":   data.get("profile_url", ""),
        "niche":         data.get("niche", ""),
        "followers":     data.get("followers"),
        "contact_email": data.get("contact_email", ""),
        "bio":           data.get("bio", ""),
        "status":        "pending",
        "created_at":    datetime.utcnow().isoformat(),
    }
    client = get_client()
    result = client.table("cs_join_requests").insert(row).execute()
    return result.data[0] if result.data else row


def list_join_requests(status: str = "pending") -> list[dict]:
    result = (get_client().table("cs_join_requests")
              .select("*").eq("status", status)
              .order("created_at", desc=True).execute())
    return result.data or []


# ── Per-customer SMTP ─────────────────────────────────────────────────────────

def _smtp_encrypt(plaintext: str) -> str:
    """Encrypt SMTP password with Fernet. Requires SMTP_ENCRYPTION_KEY env var.
    Falls back to plaintext in local dev (no key set)."""
    import os
    from cryptography.fernet import Fernet
    key = os.getenv("SMTP_ENCRYPTION_KEY", "")
    if not key:
        # Never store a customer's mailbox password in clear on the live site
        if os.getenv("VERCEL"):
            raise RuntimeError("SMTP_ENCRYPTION_KEY is not set — refusing to store an unencrypted password")
        return plaintext  # local dev — no encryption
    return Fernet(key.encode()).encrypt(plaintext.encode()).decode()


def _smtp_decrypt(ciphertext: str) -> str:
    import os
    from cryptography.fernet import Fernet
    key = os.getenv("SMTP_ENCRYPTION_KEY", "")
    if not key:
        return ciphertext
    try:
        return Fernet(key.encode()).decrypt(ciphertext.encode()).decode()
    except Exception:
        return ""  # bad key / corrupted — treat as empty


def get_smtp_config(license_key: str) -> dict | None:
    """Return decrypted SMTP config for this license, or None if not set."""
    result = (get_client().table("cs_license_smtp")
              .select("smtp_host,smtp_port,smtp_user,smtp_pass_enc,display_name,daily_cap")
              .eq("license_key", license_key).limit(1).execute())
    row = (result.data or [None])[0]
    if not row:
        return None
    return {
        "host":         row["smtp_host"],
        "port":         row["smtp_port"],
        "user":         row["smtp_user"],
        "password":     _smtp_decrypt(row["smtp_pass_enc"]),
        "display_name": row.get("display_name") or "",
        "daily_cap":    row.get("daily_cap", 50),
    }


def save_smtp_config(license_key: str, host: str, port: int, user: str,
                     password: str, display_name: str = "", daily_cap: int = 50) -> None:
    """Upsert SMTP config for a license. Password is encrypted before storage."""
    from datetime import datetime as _dt
    get_client().table("cs_license_smtp").upsert({
        "license_key":   license_key,
        "smtp_host":     host,
        "smtp_port":     int(port),
        "smtp_user":     user,
        "smtp_pass_enc": _smtp_encrypt(password),
        "display_name":  display_name or "",
        "daily_cap":     int(daily_cap),
        "updated_at":    _dt.utcnow().isoformat(),
    }, on_conflict="license_key").execute()


def delete_smtp_config(license_key: str) -> None:
    get_client().table("cs_license_smtp").delete().eq("license_key", license_key).execute()


def smtp_daily_sent(license_key: str) -> int:
    """How many real (non-dry-run) emails this license sent today."""
    from datetime import date
    today = date.today().isoformat()
    result = (get_client().table("cs_email_send_log")
              .select("recipient_count")
              .eq("license_key", license_key)
              .eq("dry_run", False)
              .gte("sent_at", today)
              .execute())
    return sum(r["recipient_count"] for r in (result.data or []))


def log_smtp_send(license_key: str, recipient_count: int, dry_run: bool) -> None:
    """Record a bulk send event for audit and daily cap."""
    get_client().table("cs_email_send_log").insert({
        "license_key":     license_key,
        "recipient_count": recipient_count,
        "dry_run":         dry_run,
    }).execute()


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
