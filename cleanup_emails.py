"""
Καθαρίζει dirty emails από τη DB:
- example@example.com (placeholder)
- *.sentry.io addresses (DSNs, όχι πραγματικά emails)
- Άλλα φανερά non-real emails
"""
import os
from dotenv import load_dotenv
load_dotenv()

from supabase import create_client

client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY"))

# Patterns που ΔΕΝ είναι πραγματικά emails
DIRTY_PATTERNS = [
    "example@example.com",
    "example@gmail.com",
    "test@test.com",
    "noreply@",
    "@sentry.io",
    "@o922922.ingest",
    "ingest.sentry",
    "@example.",
    "placeholder",
    "null@",
    "none@",
]

# Fetch όλους με email
result = client.table("cs_creators").select("id,display_name,email").eq("has_email", 1).execute()
creators = result.data or []
print(f"Found {len(creators)} creators with email")

cleaned = 0
for c in creators:
    email = c.get("email", "") or ""
    is_dirty = any(pat.lower() in email.lower() for pat in DIRTY_PATTERNS)
    if is_dirty:
        print(f"  🗑 Clearing dirty email: {c['display_name']} → {email}")
        client.table("cs_creators").update({
            "email": None,
            "has_email": 0,
        }).eq("id", c["id"]).execute()
        cleaned += 1

print(f"\n✅ Cleaned {cleaned} dirty emails. Real emails remaining: {len(creators) - cleaned}")
