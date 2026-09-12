"""
CreatorScan — FastAPI Web Server (Φάση 2 + 3)
Τρέξε με: python app.py
Dashboard:  http://localhost:8000
API docs:   http://localhost:8000/docs
API keys:   http://localhost:8000/api-keys
"""
import csv
import io
import json
import os
import smtplib
import subprocess
import sys
import threading
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Query, BackgroundTasks, Header, HTTPException, Depends, Body
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

# Auto-detect: use Supabase in production, SQLite locally
if os.getenv("SUPABASE_URL"):
    import db_cloud as db
else:
    import db

from processors.niche import NICHE_KEYWORDS

db.init_db()

app = FastAPI(title="CreatorScan API", version="2.0")

# ── Access gate ───────────────────────────────────────────────────────────────
# The dashboard, CSV export, SMTP settings, bulk send and API-key management all
# sit behind HTTP Basic auth. The live site was open to anyone with the link:
# the full email list could be downloaded and anyone could mint an API key.
# /v1/* keeps its own API-key auth. On Vercel with no ACCESS_PASSWORD set the
# app refuses every request rather than falling back to open.
import base64
import secrets
from starlette.requests import Request
from starlette.responses import Response

ACCESS_USER     = os.getenv("ACCESS_USER", "admin")
ACCESS_PASSWORD = os.getenv("ACCESS_PASSWORD", "")
ON_VERCEL       = bool(os.getenv("VERCEL"))

# Paths that never require auth
_PUBLIC_PATHS = {"/", "/join", "/api/auth/verify", "/api/join"}


def _basic_authorized(header: str) -> bool:
    if not header.startswith("Basic "):
        return False
    try:
        user, _, pw = base64.b64decode(header[6:]).decode("utf-8").partition(":")
    except Exception:
        return False
    return (secrets.compare_digest(user, ACCESS_USER)
            and secrets.compare_digest(pw, ACCESS_PASSWORD))


# Cache validated license keys for 60 s to avoid hammering Supabase
import time as _time
_lic_cache: dict[str, tuple[dict, float]] = {}
_LIC_TTL = 60.0

def _license_authorized(key: str) -> bool:
    if not key:
        return False
    now = _time.time()
    if key in _lic_cache:
        info, ts = _lic_cache[key]
        if now - ts < _LIC_TTL:
            return info is not None
    try:
        info = db.validate_license_key(key)
    except Exception:
        info = None
    _lic_cache[key] = (info, now)
    return info is not None


@app.middleware("http")
async def access_gate(request: Request, call_next):
    path = request.url.path

    # Static files & public routes — always allowed
    if path.startswith("/static/") or path in _PUBLIC_PATHS:
        return await call_next(request)

    # /v1/* keeps its own API-key auth
    if path.startswith("/v1/"):
        return await call_next(request)

    # Check license key header (primary user auth)
    lic_key = request.headers.get("X-License", "")
    if _license_authorized(lic_key):
        return await call_next(request)

    # Fallback: HTTP Basic (admin / local dev)
    if _basic_authorized(request.headers.get("authorization", "")):
        return await call_next(request)

    # Local dev without ACCESS_PASSWORD → open
    if not ACCESS_PASSWORD and not ON_VERCEL:
        return await call_next(request)

    return Response(
        '{"error":"License key required","hint":"POST /api/auth/verify with your key"}',
        status_code=401,
        media_type="application/json",
    )

# ── Serve static files ────────────────────────────────────────────────────────
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ── Scan state ────────────────────────────────────────────────────────────────
scan_state = {"running": False, "log": [], "found": 0}


def _run_scan(platform: str, niche: str, min_f: int, max_f: int):
    """Background scan thread."""
    scan_state["running"] = True
    scan_state["log"] = []
    scan_state["found"] = 0

    try:
        if platform in ("youtube", "all"):
            from collectors.youtube import YouTubeCollector
            key = os.getenv("YOUTUBE_API_KEY", "")
            if key and key != "YOUR_YOUTUBE_API_KEY_HERE":
                yt = YouTubeCollector(key)
                niches = list(NICHE_KEYWORDS.keys()) if niche == "all" else [niche]
                for n in niches:
                    scan_state["log"].append(f"🔍 YouTube · {n}...")
                    for creator in yt.scan_niche(n, min_followers=min_f, max_followers=max_f, max_per_query=20):
                        is_new = db.upsert_creator(creator)
                        if is_new:
                            scan_state["found"] += 1
                            scan_state["log"].append(
                                f"  ✅ {creator['display_name']} ({creator['followers']:,} followers)"
                            )
            else:
                scan_state["log"].append("⚠ YouTube API key δεν έχει οριστεί")

        if platform in ("twitch", "all"):
            from collectors.twitch import TwitchCollector
            cid = os.getenv("TWITCH_CLIENT_ID", "")
            sec = os.getenv("TWITCH_CLIENT_SECRET", "")
            if cid and cid != "YOUR_TWITCH_CLIENT_ID_HERE":
                tw = TwitchCollector(cid, sec)
                niches = list(NICHE_KEYWORDS.keys()) if niche == "all" else [niche]
                for n in niches:
                    scan_state["log"].append(f"🎮 Twitch · {n}...")
                    for creator in tw.scan_niche(n, min_followers=min_f, max_followers=max_f):
                        is_new = db.upsert_creator(creator)
                        if is_new:
                            scan_state["found"] += 1
                            scan_state["log"].append(
                                f"  ✅ {creator['display_name']} ({creator['followers']:,} followers)"
                            )
            else:
                scan_state["log"].append("⚠ Twitch credentials δεν έχουν οριστεί")

        if platform in ("tiktok", "all"):
            try:
                from collectors.tiktok import TikTokCollector
                tt = TikTokCollector(headless=True)
                niches = list(NICHE_KEYWORDS.keys()) if niche == "all" else [niche]
                for n in niches:
                    scan_state["log"].append(f"🎵 TikTok · {n}...")
                    for creator in tt.scan_niche(n, min_followers=min_f, max_followers=max_f):
                        is_new = db.upsert_creator(creator)
                        if is_new:
                            scan_state["found"] += 1
                            scan_state["log"].append(
                                f"  ✅ {creator['display_name']} ({creator['followers']:,} followers)"
                            )
            except ImportError:
                scan_state["log"].append("⚠ Playwright δεν είναι installed (pip install playwright && playwright install chromium)")

        if platform in ("instagram", "all"):
            try:
                from collectors.instagram import InstagramCollector
                ig = InstagramCollector(headless=True)
                niches = list(NICHE_KEYWORDS.keys()) if niche == "all" else [niche]
                for n in niches:
                    scan_state["log"].append(f"📸 Instagram · {n}...")
                    for creator in ig.scan_niche(n, min_followers=min_f, max_followers=max_f):
                        is_new = db.upsert_creator(creator)
                        if is_new:
                            scan_state["found"] += 1
                            scan_state["log"].append(
                                f"  ✅ {creator['display_name']} ({creator['followers']:,} followers)"
                            )
            except ImportError:
                scan_state["log"].append("⚠ Playwright δεν είναι installed (pip install playwright && playwright install chromium)")

    except Exception as e:
        scan_state["log"].append(f"❌ Error: {e}")
    finally:
        scan_state["running"] = False
        scan_state["log"].append("🏁 Scan ολοκληρώθηκε!")


# ── API Routes ────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the dashboard HTML."""
    html_path = STATIC_DIR / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


@app.get("/api/stats")
async def api_stats():
    return db.get_stats()


@app.get("/api/niches")
async def api_niches():
    return {"niches": sorted(NICHE_KEYWORDS.keys())}


@app.get("/api/creators")
async def api_creators(
    platform:     Optional[str] = None,
    niche:        Optional[str] = None,
    min_followers: int = 2_000,
    max_followers: int = 100_000,
    has_email:    Optional[bool] = None,
    language:     Optional[str] = None,
    search:       Optional[str] = None,
    sort:         str = "followers_desc",
    list_id:      Optional[int] = None,
    min_er:       Optional[float] = None,
    limit:        int = Query(default=50, le=500),
    offset:       int = 0,
):
    creators = db.query_creators(
        platform=platform,
        niche=niche,
        min_followers=min_followers,
        max_followers=max_followers,
        has_email=has_email,
        language=language,
        limit=limit,
        offset=offset,
        search=search,
        sort=sort,
        list_id=list_id,
        min_er=min_er,
    )
    total = db.count_creators(
        platform=platform,
        niche=niche,
        min_followers=min_followers,
        max_followers=max_followers,
        has_email=has_email,
        language=language,
        search=search,
    )
    # Attach outreach status to each creator
    try:
        outreach_map = db.get_outreach_all()
    except Exception:
        outreach_map = {}
    for c in creators:
        o = outreach_map.get(c.get("id"))
        c["outreach_status"] = o["status"] if o else "new"
        c["outreach_notes"] = o["notes"] if o else ""

    return {"creators": creators, "total": total, "offset": offset, "limit": limit}


@app.get("/api/creators/{creator_id}")
async def api_creator_detail(creator_id: int):
    """Single creator detail — για το detail drawer."""
    c = db.get_creator_by_id(creator_id)
    if not c:
        raise HTTPException(status_code=404, detail="Creator not found")
    return c


@app.get("/api/export/csv")
async def api_export_csv(
    platform:     Optional[str] = None,
    niche:        Optional[str] = None,
    min_followers: int = 2_000,
    max_followers: int = 100_000,
    has_email:    Optional[bool] = None,
):
    creators = db.query_creators(
        platform=platform, niche=niche,
        min_followers=min_followers, max_followers=max_followers,
        has_email=has_email, limit=100_000,
    )
    if not creators:
        return JSONResponse({"error": "Δεν βρέθηκαν creators"}, status_code=404)

    output = io.StringIO()
    fieldnames = ["platform", "display_name", "username", "followers", "niche",
                  "language", "email", "profile_url", "bio"]
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(creators)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=creators_export.csv"},
    )


@app.post("/api/scan/start")
async def api_scan_start(
    platform:     str = "youtube",   # youtube | twitch | tiktok | instagram | all
    niche:        str = "Gaming",
    min_followers: int = 2_000,
    max_followers: int = 100_000,
):
    if scan_state["running"]:
        return {"status": "already_running"}
    t = threading.Thread(
        target=_run_scan,
        args=(platform, niche, min_followers, max_followers),
        daemon=True,
    )
    t.start()
    return {"status": "started"}


@app.get("/api/scan/status")
async def api_scan_status():
    return {
        "running": scan_state["running"],
        "found":   scan_state["found"],
        "log":     scan_state["log"][-30:],  # last 30 lines
    }


# ── Auth — License key verify ─────────────────────────────────────────────────

@app.post("/api/auth/verify")
async def api_auth_verify(body: dict = Body(...)):
    """
    Verify a license key. Returns tier info on success.
    No auth required — this IS the auth endpoint.
    """
    key = (body.get("key") or "").strip()
    if not key:
        raise HTTPException(400, "key is required")
    info = db.validate_license_key(key)
    if not info:
        raise HTTPException(401, "Invalid or inactive license key")
    return {
        "valid": True,
        "tier":  info.get("tier", "starter"),
        "email": info.get("email", ""),
    }


# ── Creator Join (self-registration — no auth) ────────────────────────────────

@app.get("/join", response_class=HTMLResponse)
async def join_page():
    """Serve the creator self-registration page."""
    join_path = STATIC_DIR / "join.html"
    if join_path.exists():
        return HTMLResponse(content=join_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Join page not found</h1>", status_code=404)


@app.post("/api/join")
async def api_join(body: dict = Body(...)):
    """Public endpoint: creator submits their own profile."""
    platform = (body.get("platform") or "").strip().lower()
    username = (body.get("username") or "").strip()
    if not platform or not username:
        raise HTTPException(400, "platform and username are required")
    if platform not in ("youtube", "twitch", "tiktok", "instagram"):
        raise HTTPException(400, "Invalid platform")
    result = db.submit_join_request(body)
    return {"ok": True, "message": "Thanks! Your listing will be reviewed within 24 hours."}


# ── Creator Growth (follower history) ─────────────────────────────────────────

@app.get("/api/creators/{creator_id}/growth")
async def api_creator_growth(creator_id: int, days: int = 30):
    """Return follower history snapshots for a creator."""
    snapshots = db.get_creator_snapshots(creator_id, days=days)
    return {"creator_id": creator_id, "snapshots": snapshots}


# ── AI Outreach Writer ────────────────────────────────────────────────────────

@app.post("/api/ai/write-email")
async def api_ai_write_email(body: dict = Body(...)):
    """
    Use Claude to write a personalised outreach email for a creator.
    Body: {creator_id, tone, brand_name, product_name}
    """
    import anthropic as _ant

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise HTTPException(503, "AI writer not configured (ANTHROPIC_API_KEY missing)")

    creator_id = body.get("creator_id")
    if not creator_id:
        raise HTTPException(400, "creator_id required")

    c = db.get_creator_by_id(creator_id)
    if not c:
        raise HTTPException(404, "Creator not found")

    tone       = body.get("tone", "friendly")       # friendly | professional | brief
    brand_name = body.get("brand_name", "[Your Brand]")
    product    = body.get("product_name", "[Your Product]")

    followers = c.get("followers", 0) or 0
    fol_str = (f"{followers/1_000_000:.1f}M" if followers >= 1_000_000
               else f"{followers/1_000:.0f}K" if followers >= 1_000
               else str(followers))

    prompt = f"""You are a professional influencer marketing specialist.
Write a personalised outreach email for the following creator:

Name: {c.get('display_name') or c.get('username', '')}
Platform: {c.get('platform', '').capitalize()}
Followers: {fol_str}
Niche: {c.get('niche', 'General')}
Engagement Rate: {c.get('engagement_rate', 'unknown')}%
Bio: {(c.get('bio') or 'No bio available')[:300]}

Brand: {brand_name}
Product/Offer: {product}
Tone: {tone}

Write:
1. A compelling subject line (max 65 characters)
2. An email body (3–4 short paragraphs, 150–200 words max)

Rules:
- Address the creator by first name
- Reference something specific from their niche/content style
- Be genuine, not salesy
- End with a clear, low-friction CTA
- Use [Your Name] as placeholder for sender name

Respond with ONLY valid JSON, no markdown:
{{"subject": "...", "body": "..."}}"""

    client = _ant.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text.strip()

    import json as _json
    try:
        result = _json.loads(raw)
        if "subject" not in result or "body" not in result:
            raise ValueError("Missing fields")
        return {"ok": True, "subject": result["subject"], "body": result["body"]}
    except Exception:
        # Fallback: extract manually
        import re as _re
        subj = _re.search(r'"subject"\s*:\s*"([^"]+)"', raw)
        body_ = _re.search(r'"body"\s*:\s*"(.*?)"(?=\s*[,}])', raw, _re.DOTALL)
        if subj and body_:
            return {
                "ok": True,
                "subject": subj.group(1),
                "body": body_.group(1).replace("\\n", "\n"),
            }
        raise HTTPException(500, f"AI parse error: {raw[:200]}")


# ── Admin: License key management ────────────────────────────────────────────

@app.post("/api/admin/licenses")
async def api_create_license(body: dict = Body(...)):
    """Create a license key. Requires HTTP Basic admin auth (not license key)."""
    # Extra check: only allow via Basic auth (admin), not license key
    email = body.get("email", "")
    tier  = body.get("tier", "starter")
    if tier not in ("starter", "pro", "agency"):
        raise HTTPException(400, "tier must be starter | pro | agency")
    info = db.create_license_key(email=email, tier=tier)
    return {"ok": True, "key": info["key"], "tier": tier, "email": email}


@app.get("/api/admin/licenses")
async def api_list_licenses():
    """List all license keys."""
    keys = db.list_license_keys()
    for k in keys:
        k["key_masked"] = k["key"][:12] + "…" + k["key"][-4:]
    return {"keys": keys}


@app.delete("/api/admin/licenses/{key}")
async def api_revoke_license(key: str):
    ok = db.revoke_license_key(key)
    return {"ok": ok}


# ── Admin: Join requests ──────────────────────────────────────────────────────

@app.get("/api/admin/join-requests")
async def api_join_requests(status: str = "pending"):
    return {"requests": db.list_join_requests(status=status)}


# ── SMTP Settings (stored in memory, persisted via .env or runtime) ──────────
_smtp_settings: dict = {
    "host":     os.getenv("SMTP_HOST",  "smtp.gmail.com"),
    "port":     int(os.getenv("SMTP_PORT", "587")),
    "user":     os.getenv("SMTP_USER",  ""),
    "password": os.getenv("SMTP_PASS",  ""),
    "from_name": os.getenv("SMTP_FROM_NAME", "CreatorScan Outreach"),
}


@app.get("/api/settings/smtp")
async def api_get_smtp():
    """Returns SMTP settings (password masked)."""
    s = dict(_smtp_settings)
    s["password"] = "••••••••" if s["password"] else ""
    return s


@app.post("/api/settings/smtp")
async def api_set_smtp(body: dict = Body(...)):
    """Update SMTP settings at runtime."""
    for k in ("host", "port", "user", "password", "from_name"):
        if k in body and body[k] != "••••••••":
            _smtp_settings[k] = body[k]
    return {"ok": True}


@app.post("/api/settings/smtp/test")
async def api_test_smtp():
    """Send a test email to the configured SMTP user."""
    s = _smtp_settings
    if not s["user"] or not s["password"]:
        raise HTTPException(400, "SMTP not configured")
    try:
        msg = MIMEMultipart()
        msg["From"]    = f"{s['from_name']} <{s['user']}>"
        msg["To"]      = s["user"]
        msg["Subject"] = "✅ CreatorScan SMTP Test"
        msg.attach(MIMEText("<h2>SMTP works!</h2><p>CreatorScan outreach is configured correctly.</p>", "html"))
        with smtplib.SMTP(s["host"], int(s["port"]), timeout=15) as srv:
            srv.starttls()
            srv.login(s["user"], s["password"])
            srv.sendmail(s["user"], s["user"], msg.as_string())
        return {"ok": True, "msg": f"Test email sent to {s['user']}"}
    except Exception as e:
        raise HTTPException(400, str(e))


def _render_template(template: str, creator: dict) -> str:
    """Replace {{variables}} in email template with creator data."""
    followers = creator.get("followers", 0) or 0
    if followers >= 1_000_000:
        fol_str = f"{followers/1_000_000:.1f}M"
    elif followers >= 1_000:
        fol_str = f"{followers/1_000:.1f}K"
    else:
        fol_str = str(followers)

    replacements = {
        "{{creator_name}}":     creator.get("display_name") or creator.get("username", ""),
        "{{creator_username}}": f"@{creator.get('username', '')}",
        "{{platform}}":         creator.get("platform", "").capitalize(),
        "{{followers}}":        fol_str,
        "{{niche}}":            creator.get("niche", ""),
        "{{profile_url}}":      creator.get("profile_url", ""),
        "{{email}}":            creator.get("email", ""),
    }
    result = template
    for key, val in replacements.items():
        result = result.replace(key, str(val or ""))
    return result


@app.post("/api/outreach/send-bulk")
async def api_send_bulk(body: dict = Body(...)):
    """
    Send bulk outreach emails to a list of creators.
    Body: {creator_ids: [int], subject: str, body_html: str, dry_run: bool}
    """
    s = _smtp_settings
    if not s["user"] or not s["password"]:
        raise HTTPException(400, "SMTP not configured — go to Settings first")

    creator_ids: list[int] = body.get("creator_ids", [])
    subject_tpl: str       = body.get("subject", "")
    body_tpl:    str       = body.get("body_html", "")
    dry_run:     bool      = body.get("dry_run", False)

    if not creator_ids:
        raise HTTPException(400, "No creator_ids provided")
    if not subject_tpl or not body_tpl:
        raise HTTPException(400, "subject and body_html required")
    if len(creator_ids) > 100:
        raise HTTPException(400, "Max 100 emails per batch")

    results = []
    sent = 0
    failed = 0

    try:
        smtp_conn = None if dry_run else smtplib.SMTP(s["host"], int(s["port"]), timeout=20)
        if smtp_conn:
            smtp_conn.starttls()
            smtp_conn.login(s["user"], s["password"])

        for cid in creator_ids:
            creator = db.get_creator_by_id(cid)
            if not creator:
                results.append({"id": cid, "status": "not_found"})
                continue
            email = creator.get("email")
            if not email:
                results.append({"id": cid, "status": "no_email", "name": creator.get("display_name")})
                failed += 1
                continue

            rendered_subject = _render_template(subject_tpl, creator)
            rendered_body    = _render_template(body_tpl, creator)

            if dry_run:
                results.append({"id": cid, "status": "dry_run", "to": email,
                                 "subject": rendered_subject, "name": creator.get("display_name")})
                sent += 1
                continue

            try:
                msg = MIMEMultipart("alternative")
                msg["From"]    = f"{s['from_name']} <{s['user']}>"
                msg["To"]      = email
                msg["Subject"] = rendered_subject
                msg.attach(MIMEText(rendered_body, "html"))
                smtp_conn.sendmail(s["user"], email, msg.as_string())
                # Mark as contacted in outreach
                db.upsert_outreach(cid, status="contacted")
                results.append({"id": cid, "status": "sent", "to": email, "name": creator.get("display_name")})
                sent += 1
            except Exception as e:
                results.append({"id": cid, "status": "error", "to": email, "error": str(e)})
                failed += 1

        if smtp_conn:
            smtp_conn.quit()
    except Exception as e:
        raise HTTPException(500, f"SMTP connection failed: {e}")

    return {
        "sent": sent, "failed": failed, "dry_run": dry_run,
        "results": results
    }


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 3 — PUBLIC REST API  (/v1/)
# Authentication: X-API-Key header  OR  ?api_key= query param
# Docs: http://localhost:8000/docs
# ═══════════════════════════════════════════════════════════════════════════════

async def require_api_key(
    x_api_key: Optional[str] = Header(default=None),
    api_key:   Optional[str] = Query(default=None),
) -> dict:
    """FastAPI dependency — validates API key και checks rate limit."""
    key = x_api_key or api_key
    if not key:
        raise HTTPException(
            status_code=401,
            detail={
                "error":   "API key απαιτείται",
                "hint":    "Πρόσθεσε X-API-Key header ή ?api_key= query param",
                "get_key": "POST /api/keys  (από το dashboard)"
            }
        )
    allowed, info = db.check_and_increment(key)
    if info is None:
        raise HTTPException(status_code=401, detail={"error": "Άκυρο API key"})
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "error":       "Rate limit exceeded",
                "limit":       info["limit_per_day"],
                "calls_today": info["calls_today"],
                "tier":        info["tier"],
                "upgrade":     "Επικοινώνησε για Pro tier (5,000 calls/day)"
            }
        )
    return info


# ── /v1/creators ──────────────────────────────────────────────────────────────
@app.get(
    "/v1/creators",
    summary="Search creators",
    tags=["v1"],
    responses={401: {"description": "Missing / invalid API key"},
               429: {"description": "Rate limit exceeded"}},
)
async def v1_creators(
    key_info:      dict = Depends(require_api_key),
    platform:      Optional[str] = Query(None,  description="youtube | twitch | tiktok"),
    niche:         Optional[str] = Query(None,  description="Gaming | Fitness | Tech | …"),
    min_followers: int           = Query(2_000, description="Minimum followers"),
    max_followers: int           = Query(100_000, description="Maximum followers"),
    has_email:     Optional[bool]= Query(None,  description="Only creators with email in bio"),
    language:      Optional[str] = Query(None,  description="Language code: en, el, es …"),
    search:        Optional[str] = Query(None,  description="Keyword search in name/bio"),
    limit:         int           = Query(20,  le=200, description="Results per page (max 200)"),
    offset:        int           = Query(0,           description="Pagination offset"),
):
    """
    Search and filter micro-creators (2K–100K followers).

    **Authentication**: `X-API-Key: YOUR_KEY` header or `?api_key=YOUR_KEY`

    **Example**:
    ```
    GET /v1/creators?platform=youtube&niche=Gaming&min_followers=5000&limit=20
    X-API-Key: cs_your_key_here
    ```
    """
    creators = db.query_creators(
        platform=platform, niche=niche,
        min_followers=min_followers, max_followers=max_followers,
        has_email=has_email, language=language,
        search=search, limit=limit, offset=offset,
    )
    total = db.count_creators(
        platform=platform, niche=niche,
        min_followers=min_followers, max_followers=max_followers,
        has_email=has_email, language=language, search=search,
    )

    # Clean fields for API response
    public_fields = ["platform", "username", "display_name", "followers",
                     "avg_views", "posts_count", "niche", "language", "country",
                     "bio", "profile_url", "email", "has_email", "updated_at"]
    clean = [{f: c.get(f) for f in public_fields} for c in creators]

    db.log_api_usage(key_info["key"], "/v1/creators",
                     f"platform={platform}&niche={niche}&search={search}", len(clean))
    return {
        "data":        clean,
        "total":       total,
        "offset":      offset,
        "limit":       limit,
        "has_more":    offset + limit < total,
        "api_usage":   {"calls_today": key_info["calls_today"] + 1,
                        "limit_today": key_info["limit_per_day"],
                        "tier":        key_info["tier"]},
    }


# ── /v1/stats ─────────────────────────────────────────────────────────────────
@app.get("/v1/stats", summary="Database statistics", tags=["v1"])
async def v1_stats(key_info: dict = Depends(require_api_key)):
    """Returns total creator counts by platform and niche."""
    stats = db.get_stats()
    db.log_api_usage(key_info["key"], "/v1/stats", "", 1)
    return {"data": stats, "api_usage": {"calls_today": key_info["calls_today"] + 1,
                                          "tier": key_info["tier"]}}


# ── /v1/niches ────────────────────────────────────────────────────────────────
@app.get("/v1/niches", summary="List available niches", tags=["v1"])
async def v1_niches(key_info: dict = Depends(require_api_key)):
    """Returns all available niche categories."""
    from processors.niche import NICHE_KEYWORDS
    return {"data": {"niches": sorted(NICHE_KEYWORDS.keys())}}


# ── API Key Management (internal — no auth needed, local only) ────────────────
@app.post("/api/keys", summary="Create API key", tags=["keys"])
async def api_create_key(
    name: str = Query(..., description="Όνομα για το key"),
    tier: str = Query("free", description="free | pro | unlimited"),
):
    """Δημιουργεί νέο API key. Free: 100 calls/day, Pro: 5000."""
    if tier not in ("free", "pro", "unlimited"):
        raise HTTPException(400, "tier πρέπει να είναι: free, pro, unlimited")
    key_info = db.create_api_key(name=name, tier=tier)
    return {"success": True, "key": key_info}


@app.get("/api/keys", summary="List API keys", tags=["keys"])
async def api_list_keys():
    keys = db.list_api_keys()
    # Mask key for display: show first 8 + last 4
    for k in keys:
        full = k["key"]
        k["key_preview"] = full[:10] + "…" + full[-4:]
        k["key_full"] = full
    return {"keys": keys}


@app.delete("/api/keys/{key}", summary="Revoke API key", tags=["keys"])
async def api_revoke_key(key: str):
    ok = db.revoke_api_key(key)
    if not ok:
        raise HTTPException(404, "Key δεν βρέθηκε")
    return {"success": True, "message": "Key ανακλήθηκε"}


@app.get("/api/keys/{key}/usage", summary="Key usage stats", tags=["keys"])
async def api_key_usage(key: str):
    info = db.get_api_key(key)
    if not info:
        raise HTTPException(404, "Key δεν βρέθηκε")
    usage = db.get_key_usage(key, days=7)
    return {"key_info": info, "usage_last_7_days": usage}


# ── Outreach CRM ─────────────────────────────────────────────────────────────

@app.get("/api/outreach")
async def api_outreach_all():
    """Επιστρέφει όλα τα outreach records."""
    data = db.get_outreach_all()
    return {"outreach": data}


@app.patch("/api/outreach/{creator_id}")
async def api_outreach_update(
    creator_id: int,
    status: Optional[str] = Body(default=None, embed=True),
    notes:  Optional[str] = Body(default=None, embed=True),
):
    """Update outreach status/notes για creator."""
    VALID = {"new", "contacted", "replied", "interested", "passed"}
    if status and status not in VALID:
        raise HTTPException(400, f"status πρέπει να είναι: {', '.join(VALID)}")
    result = db.upsert_outreach(creator_id, status=status, notes=notes)
    return {"success": True, "outreach": result}


# ── Saved Lists ───────────────────────────────────────────────────────────────

@app.get("/api/lists")
async def api_get_lists():
    lists = db.get_lists()
    counts = db.get_list_counts()
    for lst in lists:
        lst["count"] = counts.get(lst["id"], 0)
    return {"lists": lists}


@app.post("/api/lists")
async def api_create_list(
    name:  str = Body(..., embed=True),
    color: str = Body("#6366f1", embed=True),
):
    lst = db.create_list(name=name, color=color)
    return {"success": True, "list": lst}


@app.delete("/api/lists/{list_id}")
async def api_delete_list(list_id: int):
    db.delete_list(list_id)
    return {"success": True}


@app.post("/api/lists/{list_id}/creators")
async def api_add_to_list(list_id: int, creator_id: int = Body(..., embed=True)):
    ok = db.add_to_list(list_id, creator_id)
    return {"success": ok}


@app.delete("/api/lists/{list_id}/creators/{creator_id}")
async def api_remove_from_list(list_id: int, creator_id: int):
    db.remove_from_list(list_id, creator_id)
    return {"success": True}


# ── API Keys Dashboard page ───────────────────────────────────────────────────
@app.get("/api-keys", response_class=HTMLResponse)
async def api_keys_page():
    keys_page = STATIC_DIR / "api-keys.html"
    return HTMLResponse(content=keys_page.read_text(encoding="utf-8"))


# ── Run ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import webbrowser
    print("\n🔍 CreatorScan Dashboard + API")
    print("   Dashboard: http://localhost:8000")
    print("   API docs:  http://localhost:8000/docs")
    print("   API keys:  http://localhost:8000/api-keys\n")
    webbrowser.open("http://localhost:8000")
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
