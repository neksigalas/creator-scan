"""
Related Channels Expander — εκθετική ανάπτυξη DB μέσω Featured Channels.

Παίρνει τους ήδη υπάρχοντες YouTube creators από τη DB,
scrape-άρει τα "related channels" από το channels tab κάθε creator,
και προσθέτει τα νέα channels στη DB.

Αποτέλεσμα: αν έχουμε 500 YT creators → ~4000 νέα (8 related ανά channel)

Usage:
    python expand_related.py            # όλοι οι YT creators στη DB
    python expand_related.py 100        # μόνο τα πρώτα 100
    python expand_related.py 100 2      # 2 rounds (related of related)
"""
import os
import sys
import time
import dotenv

dotenv.load_dotenv()

from db_cloud import get_client, upsert_creator, get_stats
from collectors.youtube import YouTubeCollector, scrape_related_channel_ids

MAX_SEED  = int(sys.argv[1]) if len(sys.argv) > 1 else 500
ROUNDS    = int(sys.argv[2]) if len(sys.argv) > 2 else 1
BATCH_SIZE = 50  # API channels.list accepts up to 50 IDs
MIN_FOLLOWERS = 2_000
MAX_FOLLOWERS = 100_000

client = get_client()
yt = YouTubeCollector(api_key=os.environ["YOUTUBE_API_KEY"])

print(f"=== Related Channels Expander ===")
print(f"Seed: up to {MAX_SEED} YT creators | {ROUNDS} round(s)")
before = get_stats()
print(f"DB before: {before.get('total', '?')} creators")
print()

# Load seed channel IDs from DB
result = (client.table("cs_creators")
          .select("platform_id,platform,niche")
          .eq("platform", "youtube")
          .limit(MAX_SEED)
          .execute())

seed_rows = result.data or []
seed_ids   = [r["platform_id"] for r in seed_rows if r.get("platform_id")]
seed_niches = {r["platform_id"]: r.get("niche", "Gaming") for r in seed_rows}

print(f"Loaded {len(seed_ids)} seed YouTube channel IDs")
print()

already_seen: set[str] = set(seed_ids)
total_added = 0
current_seeds = seed_ids

for round_num in range(1, ROUNDS + 1):
    print(f"--- Round {round_num}/{ROUNDS} ---")
    all_related_ids: list[str] = []

    for i, channel_id in enumerate(current_seeds):
        if i % 50 == 0:
            print(f"  Scanning seed {i+1}/{len(current_seeds)}...")
        profile_url = f"https://www.youtube.com/channel/{channel_id}"
        related = scrape_related_channel_ids(profile_url, max_results=10)
        for rid in related:
            if rid not in already_seen:
                already_seen.add(rid)
                all_related_ids.append(rid)
        time.sleep(0.4)  # polite delay

    print(f"  Found {len(all_related_ids)} new related channel IDs")
    if not all_related_ids:
        print("  Nothing new — stopping.")
        break

    # Fetch details in batches of 50
    added_this_round = 0
    for batch_start in range(0, len(all_related_ids), BATCH_SIZE):
        batch = all_related_ids[batch_start:batch_start + BATCH_SIZE]
        print(f"  Fetching batch {batch_start//BATCH_SIZE + 1}: {len(batch)} channels...")
        creators = yt.get_channel_details(batch)
        for c in creators:
            if MIN_FOLLOWERS <= c["followers"] <= MAX_FOLLOWERS:
                upsert_creator(c)
                added_this_round += 1

    total_added += added_this_round
    print(f"  + Added {added_this_round} creators this round")
    current_seeds = all_related_ids  # next round seeds = this round's related

after = get_stats()
print()
print(f"=== Done ===")
print(f"Total added: {total_added}")
print(f"DB after: {after.get('total', '?')} creators")
