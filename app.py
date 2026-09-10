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
import subprocess
import sys
import threading
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
    return {"creators": creators, "total": total, "offset": offset, "limit": limit}


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
