"""
Deep scan — τρέχει scan για όλα τα niches, πολλαπλές φορές,
με expanded queries. Στόχος: 2000+ creators στη DB.

Usage: python scan_deep.py [rounds]
"""
import subprocess
import sys
import time

NICHES = [
    "Gaming", "Fitness", "Tech", "Beauty", "Food", "Travel",
    "Finance", "Education", "Fashion", "Music", "Art & Design",
    "Comedy", "Lifestyle", "Parenting", "DIY & Crafts",
    "Sports", "Pets & Animals", "Business",
]

ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 2
print(f"🚀 Deep Scan — {ROUNDS} rounds × {len(NICHES)} niches = {ROUNDS * len(NICHES)} scans")
print(f"   YouTube: up to 12 queries × 50 results × {len(NICHES)} niches = ~{12*50*len(NICHES)} channel checks/round")
print()

total_errors = 0
for round_num in range(1, ROUNDS + 1):
    print(f"\n{'='*60}")
    print(f"ROUND {round_num}/{ROUNDS}")
    print(f"{'='*60}")

    for i, niche in enumerate(NICHES, 1):
        print(f"\n[{i}/{len(NICHES)}] Niche: {niche}")
        result = subprocess.run(
            [sys.executable, "main.py", "scan",
             "--platform", "all",
             "--niche", niche],
            capture_output=False,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            print(f"  [!] Error (code {result.returncode})")
            total_errors += 1
        # Small pause between niches
        time.sleep(2)

print(f"\n\n{'='*60}")
print(f"✅ Deep scan complete — {total_errors} errors total")
print(f"   Check DB count: python -c \"import db_cloud; print(db_cloud.get_stats())\"")
