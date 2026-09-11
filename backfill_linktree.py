"""
Backfill emails: ψάχνει Linktree/Beacons/channel-links για creators που
ΔΕΝ έχουν email. Για YouTube: scrapes το channel About page.
Για άλλες πλατφόρμες: ψάχνει link-in-bio URLs στο bio.

Τρέξε: python backfill_linktree.py
"""
import os, sys, time, re
sys.path.insert(0, r'C:\BinanceAgent\creator-scan')
from dotenv import load_dotenv
load_dotenv(r'C:\BinanceAgent\creator-scan\.env')

from supabase import create_client
from processors.linktree import find_email_via_linkinbio, scrape_generic, EMAIL_PATTERN
from collectors.youtube import scrape_youtube_channel_links

URL = os.environ["SUPABASE_URL"]
KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
client = create_client(URL, KEY)

print("📧 Email Backfill — Linktree + YouTube Channel Links")
print("=" * 55)

# Fetch creators χωρίς email
result = (client.table("cs_creators")
          .select("id,platform,display_name,username,bio,profile_url")
          .eq("has_email", 0)
          .execute())
creators = result.data or []
print(f"Found {len(creators)} creators χωρίς email\n")

found = 0
checked = 0

for i, c in enumerate(creators, 1):
    platform = c.get("platform", "")
    name = (c.get("display_name") or c.get("username") or "?")[:30]
    bio  = c.get("bio") or ""
    profile_url = c.get("profile_url") or ""

    email = None

    # 1. Ψάξε email μέσω link-in-bio URL στο bio
    if bio:
        email = find_email_via_linkinbio(bio)

    # 2. Για YouTube: scrape το channel about page για external links
    if not email and platform == "youtube" and profile_url:
        try:
            ext_links = scrape_youtube_channel_links(profile_url)
            for link in ext_links:
                scraped = find_email_via_linkinbio(link) or scrape_generic(link)
                if scraped:
                    email = scraped
                    break
        except Exception:
            pass

    checked += 1
    if email:
        found += 1
        print(f"[{i}] ✅ {name} ({platform}): {email}")
        client.table("cs_creators").update({
            "email":     email,
            "has_email": 1,
        }).eq("id", c["id"]).execute()
    else:
        if i % 20 == 0:
            print(f"[{i}/{len(creators)}] checked {checked}, found {found}...")

    time.sleep(0.3)

print(f"\n{'='*55}")
print(f"✅ Done! {found}/{checked} νέα emails βρέθηκαν.")
