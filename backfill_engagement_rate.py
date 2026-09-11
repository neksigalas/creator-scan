"""
Backfill engagement_rate για όλους τους υπάρχοντες creators στη Supabase.
YouTube ER = avg_views / followers × 100
Twitch ER  = avg_views / followers × 100 (avg_views = live viewers για Twitch)

Τρέξε: python backfill_engagement_rate.py
"""
import os
from dotenv import load_dotenv

load_dotenv(r'C:/BinanceAgent/creator-scan/.env')

from supabase import create_client

URL = os.environ["SUPABASE_URL"]
KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
client = create_client(URL, KEY)

print("📊 Fetching creators...")
result = client.table("cs_creators").select("id,platform,followers,avg_views,engagement_rate").execute()
creators = result.data or []
print(f"   {len(creators)} creators found")

updated = 0
skipped = 0
batch = []

for c in creators:
    followers = c.get("followers") or 0
    avg_views = c.get("avg_views") or 0

    if followers > 0 and avg_views > 0:
        er = round(avg_views / followers * 100, 2)
        batch.append({"id": c["id"], "engagement_rate": er})
    else:
        skipped += 1

print(f"   Calculating ER for {len(batch)} creators, skipping {skipped}...")

# Update in batches of 100
for i in range(0, len(batch), 100):
    chunk = batch[i:i+100]
    for row in chunk:
        client.table("cs_creators").update(
            {"engagement_rate": row["engagement_rate"]}
        ).eq("id", row["id"]).execute()
    updated += len(chunk)
    print(f"   ✅ Updated {updated}/{len(batch)}...")

print(f"\n✅ Done! {updated} creators με ER, {skipped} χωρίς δεδομένα.")

# Show distribution
high   = sum(1 for b in batch if b["engagement_rate"] > 5)
medium = sum(1 for b in batch if 2 <= b["engagement_rate"] <= 5)
low    = sum(1 for b in batch if b["engagement_rate"] < 2)
print(f"\n📈 Κατανομή:")
print(f"   🟢 Υψηλό (>5%):  {high}")
print(f"   🟡 Μέτριο (2-5%): {medium}")
print(f"   🔴 Χαμηλό (<2%): {low}")
