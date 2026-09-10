"""
YouTube collector — hybrid approach:
  1. Scrape YouTube search results (ZERO API quota) → channel IDs
  2. channels.list API (1 unit per 50 channels) → stats & details

Αποτέλεσμα: 10,000 units/day = ~500,000 channel lookups/day (vs. 100 searches).
"""
import json
import os
import re
import time
from typing import Generator

import requests
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from rich.console import Console

from processors.niche import classify_niche, extract_email

console = Console()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

NICHE_QUERIES: dict[str, list[str]] = {
    "Gaming":       ["gaming channel", "let's play youtube", "esports streamer", "indie game"],
    "Fitness":      ["fitness channel", "workout youtube", "gym vlog", "personal trainer"],
    "Tech":         ["tech review channel", "coding tutorial", "programming youtube", "software dev"],
    "Beauty":       ["makeup tutorial", "skincare routine", "beauty tips youtube"],
    "Food":         ["cooking channel", "recipe youtube", "food vlog", "chef tips"],
    "Travel":       ["travel vlog", "adventure channel", "digital nomad", "travel tips"],
    "Finance":      ["investing youtube", "personal finance channel", "crypto education"],
    "Education":    ["educational channel", "learn online", "science explained", "tutorial youtube"],
    "Fashion":      ["fashion vlog", "outfit ideas", "style youtube", "lookbook"],
    "Music":        ["musician channel", "original music youtube", "covers channel", "singer vlog"],
    "Art & Design": ["art channel", "drawing tutorials", "digital art youtube", "illustrator"],
    "Comedy":       ["comedy channel", "funny sketches youtube", "humor creator"],
    "Lifestyle":    ["lifestyle vlog", "daily routine channel", "self improvement youtube"],
    "Parenting":    ["mom vlog", "dad vlog", "parenting channel", "family youtube"],
    "DIY & Crafts": ["diy channel", "crafts tutorial", "woodworking youtube"],
    "Sports":       ["sports channel", "football analysis", "training vlog", "athlete youtube"],
    "Pets & Animals": ["dog channel", "cat youtube", "animal rescue vlog", "pet care"],
    "Business":     ["entrepreneur vlog", "startup journey", "business tips youtube", "side hustle"],
}


def scrape_youtube_channel_ids(query: str, max_results: int = 30) -> list[str]:
    """
    Scrapes YouTube search results (type=channel) → channel IDs.
    ZERO API quota cost. Uses ytInitialData embedded JSON.
    """
    url = "https://www.youtube.com/results"
    params = {"search_query": query, "sp": "EgIQAg%3D%3D"}  # sp = filter: channels only

    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        console.print(f"[yellow]⚠ Scrape error: {e}[/yellow]")
        return []

    # Extract ytInitialData JSON from page source
    match = re.search(r"var ytInitialData\s*=\s*(\{.+?\});</script>", resp.text, re.DOTALL)
    if not match:
        console.print("[yellow]⚠ Δεν βρέθηκε ytInitialData[/yellow]")
        return []

    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        console.print("[yellow]⚠ JSON parse error στο ytInitialData[/yellow]")
        return []

    channel_ids: list[str] = []

    def extract_channel_ids(obj):
        if len(channel_ids) >= max_results:
            return
        if isinstance(obj, dict):
            # Channel renderer patterns
            for key in ("channelRenderer", "gridChannelRenderer"):
                if key in obj:
                    ch = obj[key]
                    cid = ch.get("channelId")
                    if cid and cid not in channel_ids:
                        channel_ids.append(cid)
            # Browse endpoint (another pattern)
            if "browseEndpoint" in obj:
                ep = obj["browseEndpoint"]
                cid = ep.get("browseId", "")
                if cid.startswith("UC") and cid not in channel_ids:
                    channel_ids.append(cid)
            for v in obj.values():
                extract_channel_ids(v)
        elif isinstance(obj, list):
            for item in obj:
                extract_channel_ids(item)

    extract_channel_ids(data)
    return channel_ids[:max_results]


class YouTubeCollector:
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("YouTube API key απαιτείται!")
        self.api_key = api_key
        self._service = None

    def _get_service(self):
        if self._service is None:
            self._service = build("youtube", "v3", developerKey=self.api_key)
        return self._service

    def get_channel_details(self, channel_ids: list[str]) -> list[dict]:
        """
        Παίρνει στατιστικά για batch channel IDs.
        Κόστος: μόνο 1 unit ανά call (έως 50 channels/call).
        """
        if not channel_ids:
            return []

        svc = self._get_service()
        results = []

        for i in range(0, len(channel_ids), 50):
            batch = channel_ids[i : i + 50]
            try:
                resp = svc.channels().list(
                    part="snippet,statistics,brandingSettings",
                    id=",".join(batch),
                ).execute()
            except HttpError as e:
                if e.resp.status == 403:
                    console.print("[red]⚠ YouTube API quota εξαντλήθηκε![/red]")
                    break
                console.print(f"[yellow]Channel details error: {e}[/yellow]")
                continue

            for item in resp.get("items", []):
                stats   = item.get("statistics", {})
                snippet = item.get("snippet", {})
                branding = item.get("brandingSettings", {}).get("channel", {})

                sub_count = stats.get("subscriberCount")
                if sub_count is None:
                    continue
                sub_count = int(sub_count)

                video_count = int(stats.get("videoCount", 0))
                view_count  = int(stats.get("viewCount", 0))
                avg_views   = (view_count // video_count) if video_count > 0 else 0

                description  = snippet.get("description", "")
                keywords_str = branding.get("keywords", "")
                combined     = f"{description} {keywords_str} {snippet.get('title', '')}"

                niche, niches = classify_niche(combined)
                email         = extract_email(description)

                custom_url = snippet.get("customUrl", "")
                profile_url = (
                    f"https://www.youtube.com/{custom_url}"
                    if custom_url else
                    f"https://www.youtube.com/channel/{item['id']}"
                )

                results.append({
                    "platform":        "youtube",
                    "platform_id":     item["id"],
                    "username":        (custom_url or item["id"]).lstrip("@"),
                    "display_name":    snippet.get("title", ""),
                    "followers":       sub_count,
                    "following":       None,
                    "posts_count":     video_count,
                    "avg_views":       avg_views,
                    "engagement_rate": None,
                    "niche":           niche,
                    "niches":          niches,
                    "language":        snippet.get("defaultLanguage") or snippet.get("country"),
                    "country":         snippet.get("country"),
                    "bio":             description[:1000],
                    "profile_url":     profile_url,
                    "avatar_url":      (
                        snippet.get("thumbnails", {})
                        .get("high", {})
                        .get("url", "")
                    ),
                    "email":           email,
                    "has_email":       1 if email else 0,
                    "tags":            [
                        kw.strip().strip('"')
                        for kw in keywords_str.split()
                        if kw.strip()
                    ][:20],
                })

            time.sleep(0.15)

        return results

    def scan_niche(
        self,
        niche: str,
        min_followers: int = 2_000,
        max_followers: int = 100_000,
        max_per_query: int = 30,
    ) -> Generator[dict, None, None]:
        """
        Σκανάρει μια niche:
        1. Scrape YouTube search (free) → channel IDs
        2. channels.list API (1 unit/50 channels) → stats
        3. Φιλτράρει κατά follower range
        """
        queries = NICHE_QUERIES.get(niche, [niche])
        seen_ids: set[str] = set()

        for query in queries:
            console.print(f"  🔍 Scraping YouTube: [cyan]{query}[/cyan]")
            channel_ids = scrape_youtube_channel_ids(query, max_results=max_per_query)
            new_ids = [cid for cid in channel_ids if cid not in seen_ids]
            seen_ids.update(new_ids)

            if not new_ids:
                console.print(f"    [dim]Δεν βρέθηκαν νέα channels[/dim]")
                continue

            console.print(f"    → {len(new_ids)} channels, fetching stats via API...")
            details = self.get_channel_details(new_ids)

            in_range = 0
            for creator in details:
                if min_followers <= creator["followers"] <= max_followers:
                    in_range += 1
                    yield creator

            console.print(
                f"    ✓ {len(details)} channels checked, "
                f"[green]{in_range} in range[/green]"
            )
            time.sleep(1.0)  # πολύ polite delay για scraping

    def scan_custom_query(
        self,
        query: str,
        min_followers: int = 2_000,
        max_followers: int = 100_000,
        max_results: int = 50,
    ) -> Generator[dict, None, None]:
        """Σκανάρει με custom search query."""
        console.print(f"  🔍 Scraping YouTube: [cyan]{query}[/cyan]")
        channel_ids = scrape_youtube_channel_ids(query, max_results=max_results)
        details = self.get_channel_details(channel_ids)
        for creator in details:
            if min_followers <= creator["followers"] <= max_followers:
                yield creator
