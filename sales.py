"""
CreatorScan — selling side (DigitalDrop)
=========================================
Everything a stranger needs to go from "never heard of it" to a working
license, with no human in the loop:

  GET  /              landing page (static/landing.html) — the app moved to /app
  GET  /pricing       same page, pricing section
  GET  /privacy       privacy notice (we hold third parties' public business data)
  GET  /remove        removal request form for creators listed here
  POST /api/remove    stores a removal request
  POST /api/webhooks/whop
       membership.activated   → create a license for the buyer's email and tier,
                                email the key from the DigitalDrop account
       membership.deactivated → revoke that email's licenses

The app itself (search, profiles, AI writer) lives in app.py and belongs to the
CreatorScan session; this file only sells and delivers access to it.

Env (Vercel): WHOP_WEBHOOK_SECRET, WHOP_PLAN_STARTER, WHOP_PLAN_PRO,
              GMAIL_USER, GMAIL_APP_PASSWORD
"""
import base64
import hashlib
import hmac
import json
import os
import smtplib
import time
from email.mime.text import MIMEText
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

if os.getenv("SUPABASE_URL"):
    import db_cloud as db
else:
    import db

router = APIRouter()
STATIC = Path(__file__).parent / "static"
APP_URL = os.getenv("PUBLIC_APP_URL", "https://creator-scan.vercel.app")

# Plan → tier. Plan ids come from env so a new price never needs a deploy of
# code; the plan's own metadata.tier is the fallback.
PLAN_TIERS = {p: t for p, t in ((os.getenv("WHOP_PLAN_STARTER"), "starter"),
                                 (os.getenv("WHOP_PLAN_PRO"), "pro")) if p}


def _page(name: str) -> HTMLResponse:
    return HTMLResponse((STATIC / name).read_text(encoding="utf-8"))


@router.get("/", response_class=HTMLResponse)
async def landing():
    return _page("landing.html")


_FAVICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="8" fill="#0E6B5C"/>'
            '<circle cx="14" cy="14" r="7" fill="none" stroke="#fff" stroke-width="3"/>'
            '<path d="M19 19l6 6" stroke="#fff" stroke-width="3" stroke-linecap="round"/></svg>')


@router.get("/favicon.ico")
async def favicon():
    # Browsers ask for it on every page; unanswered it logged a 401 in customers' consoles
    return Response(_FAVICON, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=604800"})


@router.get("/pricing", response_class=HTMLResponse)
async def pricing():
    return _page("landing.html")


@router.get("/privacy", response_class=HTMLResponse)
async def privacy():
    return _page("privacy.html")


@router.get("/remove", response_class=HTMLResponse)
async def remove_page():
    return _page("remove.html")


@router.post("/api/remove")
async def remove_request(body: dict = Body(...)):
    profile = (body.get("profile_url") or "").strip()[:300]
    email = (body.get("email") or "").strip()[:200]
    if not profile or "." not in profile:
        raise HTTPException(400, "Please give the link to your channel or profile.")
    if "@" not in email:
        raise HTTPException(400, "Please give an email address we can confirm the request with.")
    row = {"profile_url": profile, "email": email,
           "reason": (body.get("reason") or "").strip()[:1000], "status": "new"}
    try:
        db.get_client().table("cs_removal_requests").insert(row).execute()
    except Exception as e:                       # never lose a request silently
        print(f"[remove] could not store request {row}: {e}")
        raise HTTPException(500, "We could not save your request. Please email us instead.")
    _send_mail(os.getenv("GMAIL_USER", ""), "CreatorScan removal request",
               f"New removal request\n\nProfile: {profile}\nEmail: {email}\nReason: {row['reason'] or '-'}\n")
    return {"ok": True}


# ── Whop webhook ─────────────────────────────────────────────────────────────
# Standard Webhooks, as Whop documents them: webhook-id, webhook-timestamp and
# webhook-signature "v1,<base64>" (space-separated if several), where the
# signature is HMAC-SHA256 over "id.timestamp.body". The ws_ secret is used as
# the key as-is; the base64 decoding of the part after the prefix (the Standard
# Webhooks convention) is accepted too.
def _verify(headers, raw: bytes) -> bool:
    secret = os.getenv("WHOP_WEBHOOK_SECRET", "")
    wid, ts, sig = headers.get("webhook-id"), headers.get("webhook-timestamp"), headers.get("webhook-signature")
    if not (secret and wid and ts and sig):
        return False
    try:
        if abs(time.time() - int(ts)) > 300:
            return False
    except ValueError:
        return False
    keys = [secret.encode()]
    try:
        keys.append(base64.b64decode(secret.split("_", 1)[-1] + "=="))
    except Exception:
        pass
    signed = f"{wid}.{ts}.".encode() + raw
    given = [p.split(",", 1)[1] for p in sig.split() if "," in p]
    for k in keys:
        mac = base64.b64encode(hmac.new(k, signed, hashlib.sha256).digest()).decode()
        if any(hmac.compare_digest(mac, g) for g in given):
            return True
    return False


def _send_mail(to: str, subject: str, text: str) -> bool:
    user, pw = os.getenv("GMAIL_USER", ""), os.getenv("GMAIL_APP_PASSWORD", "")
    if not (to and user and pw):
        print(f"[mail] not sent (missing config or recipient): {subject}")
        return False
    msg = MIMEText(text, "plain", "utf-8")
    msg["Subject"], msg["From"], msg["To"] = subject, f"CreatorScan by DigitalDrop <{user}>", to
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as s:
            s.starttls()
            s.login(user, pw)
            s.sendmail(user, [to], msg.as_string())
        return True
    except Exception as e:
        print(f"[mail] failed to {to}: {e}")
        return False


def _licenses_for(email: str) -> list:
    return [l for l in db.list_license_keys()
            if (l.get("email") or "").lower() == email.lower() and l.get("active")]


def _activate(m: dict) -> dict:
    email = ((m.get("user") or {}).get("email") or "").strip()
    plan = m.get("plan") or {}
    tier = PLAN_TIERS.get(plan.get("id")) or (plan.get("metadata") or {}).get("tier")
    if not email:
        return {"error": "no_email"}          # needs the member:email:read permission
    if tier not in ("starter", "pro", "agency"):
        return {"error": f"unknown plan {plan.get('id')}"}

    existing = _licenses_for(email)
    if any(l.get("tier") == tier for l in existing):
        return {"ok": True, "note": "already licensed"}     # Whop retries: stay idempotent
    for l in existing:                                       # plan change: one live key per buyer
        db.revoke_license_key(l["key"])
    key = db.create_license_key(email=email, tier=tier)["key"]

    sent = _send_mail(email, "Your CreatorScan license key", f"""Thanks for trying CreatorScan.

Your license key ({tier.capitalize()} plan):

    {key}

To start:
1. Open {APP_URL}/app
2. Paste the key when asked. It stays signed in on that browser.

Your trial and billing are handled by Whop; you can cancel from your Whop
account at any time, and the key stops working when the membership ends.

Questions or problems: just reply to this email.

CreatorScan by DigitalDrop
""")
    return {"ok": True, "tier": tier, "emailed": sent}


def _deactivate(m: dict) -> dict:
    email = ((m.get("user") or {}).get("email") or "").strip()
    if not email:
        return {"error": "no_email"}
    revoked = [db.revoke_license_key(l["key"]) for l in _licenses_for(email)]
    return {"ok": True, "revoked": len(revoked)}


def _ours(m: dict) -> bool:
    """Whop webhooks are company-wide: a Dental Case Preflight membership arrives
    here too. Only act on CreatorScan's own product, or a cancelled dental plan
    would revoke a CreatorScan key held under the same email."""
    want = os.getenv("WHOP_PRODUCT_ID", "")
    got = (m.get("product") or {}).get("id") or m.get("product_id")
    return not want or got == want


@router.post("/api/webhooks/whop")
async def whop_webhook(request: Request):
    raw = await request.body()
    if not _verify(request.headers, raw):
        print("[whop] rejected: bad or missing signature; headers:", ",".join(request.headers.keys()))
        return JSONResponse({"error": "invalid_signature"}, status_code=401)
    try:
        event = json.loads(raw)
    except ValueError:
        return JSONResponse({"error": "invalid_json"}, status_code=400)
    kind, data = event.get("type") or event.get("action"), event.get("data") or {}
    if not _ours(data):
        result = {"skipped": "other product"}
    elif kind in ("membership.activated", "membership.went_valid"):
        result = _activate(data)
    elif kind in ("membership.deactivated", "membership.went_invalid"):
        result = _deactivate(data)
    else:
        result = {"skipped": kind}
    print(f"[whop] {kind}: {result}")
    return {"received": True, "type": kind, "result": result}
