"""
Scan όλα τα niches με --platform all.
Τρέξε: python scan_all_niches.py
"""
import subprocess, sys, time

NICHES = [
    "Fitness", "Tech", "Beauty", "Food", "Travel",
    "Finance", "Education", "Fashion", "Music", "Art & Design",
    "Comedy", "Lifestyle", "Parenting", "DIY & Crafts",
    "Sports", "Pets & Animals", "Business",
]

print(f"=== CreatorScan — Mass Scan ({len(NICHES)} niches × all platforms) ===\n")

for i, niche in enumerate(NICHES, 1):
    print(f"\n[{i}/{len(NICHES)}] Niche: {niche}")
    print("-" * 50)
    result = subprocess.run(
        [sys.executable, "main.py", "scan", "--platform", "all", "--niche", niche],
        cwd=r"C:\BinanceAgent\creator-scan",
        env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
    )
    if result.returncode != 0:
        print(f"  [!] Error on {niche} (code {result.returncode}), continuing...")
    time.sleep(2)  # μικρή παύση μεταξύ niches

print("\n\n=== Mass Scan ολοκληρώθηκε! ===")
