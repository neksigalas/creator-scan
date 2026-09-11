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
from processors.linktree import find_email_via_linkinbio, scrape_generic, EMAIL_PATTERN

console = Console()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    # Bypass EU GDPR consent page
    # Bypass EU GDPR consent page (SOCS=CAI = accept minimal)
    "Cookie": "SOCS=CAI",
}

NICHE_QUERIES: dict[str, list[str]] = {
    "Gaming": [
        "indie game review channel", "small gaming channel 2024",
        "let's play indie games", "cozy gaming channel",
        "retro gaming youtube", "gaming tips small channel",
        "underrated gaming youtuber", "pc gaming setup tour",
        "horror game let's play", "strategy game channel",
        "mobile gaming channel", "game dev youtuber",
    ],
    "Fitness": [
        "home workout channel", "calisthenics youtube",
        "beginner fitness journey", "personal trainer vlog",
        "weight loss transformation channel", "yoga channel small",
        "running vlog channel", "powerlifting channel",
        "fitness motivation channel", "gym progress youtube",
    ],
    "Tech": [
        "budget tech review channel", "coding projects youtube",
        "software engineering vlog", "small tech youtuber",
        "python tutorial channel", "web development channel",
        "linux channel", "cybersecurity youtuber",
        "ai tools review channel", "tech unboxing small channel",
    ],
    "Beauty": [
        "indie makeup brand review", "affordable skincare channel",
        "small beauty youtuber", "natural hair tutorial channel",
        "mens grooming channel", "asian beauty channel",
        "clean beauty youtube", "drugstore makeup tutorial",
        "nail art small channel", "beauty tips beginner",
    ],
    "Food": [
        "home cook youtube channel", "budget meal prep channel",
        "street food vlog", "baking channel small",
        "vegan recipe youtube", "meal prep for weight loss",
        "cooking with limited ingredients", "international recipes channel",
        "bbq and grilling youtube", "food science channel",
    ],
    "Travel": [
        "solo travel vlog small channel", "budget travel tips youtube",
        "van life channel", "travel hacks youtuber",
        "backpacker vlog", "road trip youtube channel",
        "travel with family channel", "expat life vlog",
        "hidden gem destinations youtube", "travel photographer vlog",
    ],
    "Finance": [
        "personal finance beginners channel", "dividend investing youtube",
        "frugal living channel", "financial independence youtube",
        "passive income ideas channel", "stock market small youtuber",
        "saving money tips youtube", "crypto beginners channel",
        "real estate investing beginner", "budget finance tips youtube",
    ],
    "Education": [
        "science explainer channel", "history youtube small channel",
        "math tutorial channel", "language learning youtube",
        "philosophy channel small", "psychology explainer youtube",
        "study with me channel", "book summary channel",
        "learn programming small channel", "online course creator vlog",
    ],
    "Fashion": [
        "thrift flip channel", "sustainable fashion youtube",
        "outfit of the day small channel", "mens style youtube",
        "fashion on a budget channel", "style tips small youtuber",
        "fashion haul small channel", "fashion designer vlog",
        "capsule wardrobe youtube", "vintage fashion channel",
    ],
    "Music": [
        "original music small channel", "music producer vlog",
        "singer songwriter youtube", "bedroom music producer",
        "cover songs small channel", "guitar tutorial channel small",
        "music theory youtube", "rap freestyle channel",
        "indie musician channel", "drum cover small channel",
    ],
    "Art & Design": [
        "digital art speed paint channel", "illustration youtube small",
        "graphic designer vlog", "watercolor painting channel",
        "art process video small youtuber", "ui ux design channel",
        "character design youtube", "street art channel",
        "art supply review channel", "procreate tutorial channel",
    ],
    "Comedy": [
        "sketch comedy small channel", "stand up comedian vlog",
        "funny daily life youtube", "comedy skit small youtuber",
        "reaction channel small", "parody youtube channel",
        "meme review channel", "comedy commentary channel",
    ],
    "Lifestyle": [
        "morning routine small channel", "minimalism youtube",
        "productivity vlog small", "self improvement channel small",
        "day in the life small youtuber", "slow living channel",
        "apartment tour youtube", "reading vlog channel",
        "journaling youtube", "mental health youtube channel",
    ],
    "Parenting": [
        "new mom youtube channel", "dad vlog small",
        "homeschool family channel", "pregnancy vlog",
        "toddler activities youtube", "parenting tips small channel",
        "single parent vlog", "adoptive family youtube",
        "gentle parenting channel", "baby development youtube",
    ],
    "DIY & Crafts": [
        "beginner woodworking channel", "diy home decor small",
        "resin art youtube", "thrift flip crafts channel",
        "knitting crochet youtube", "diy budget projects channel",
        "soap making channel", "pottery youtube channel",
        "upcycling diy small youtuber", "miniature crafts channel",
    ],
    "Sports": [
        "amateur athlete youtube", "local sports vlog",
        "fitness sport training channel", "basketball training small channel",
        "soccer skills youtube", "swimming technique channel",
        "tennis lesson youtube", "martial arts channel small",
        "cycling vlog small youtuber", "extreme sports small channel",
    ],
    "Pets & Animals": [
        "dog training youtube channel", "cat behavior channel",
        "exotic pets youtube", "aquarium fish channel",
        "rabbit care channel", "bird keeping youtube",
        "rescue animal vlog", "pet care beginner channel",
        "dog breed review channel", "funny animals small channel",
    ],
    "Business": [
        "small business owner vlog", "etsy seller youtube",
        "dropshipping beginner channel", "freelancer vlog",
        "online business tips small channel", "social media marketing youtube",
        "ecommerce tips channel", "agency owner vlog",
        "content creator business channel", "solopreneur youtube",
    ],
}


def _find_all_by_key(obj, key, results=None):
    """Recursive JSON walker — βρίσκει όλα τα values για ένα key."""
    if results is None:
        results = []
    if isinstance(obj, dict):
        if key in obj:
            results.append(obj[key])
        for v in obj.values():
            _find_all_by_key(v, key, results)
    elif isinstance(obj, list):
        for item in obj:
            _find_all_by_key(item, key, results)
    return results


def scrape_youtube_channel_links(channel_url: str) -> list[str]:
    """
    Scrapes YouTube channel About page → εξωτερικά links (Linktree, Instagram, κτλ).
    Χρησιμοποιεί channelExternalLinkViewModel από ytInitialData JSON.
    Cookie SOCS=CAI: bypass EU GDPR consent.
    """
    try:
        resp = requests.get(channel_url + "/about", headers=HEADERS, timeout=12)
        match = re.search(r"var ytInitialData\s*=\s*(\{.+?\});</script>", resp.text, re.DOTALL)
        if not match:
            return []
        data = json.loads(match.group(1))

        # channelExternalLinkViewModel → link.content = "twitter.com/MKBHD" κτλ
        ext_entries = _find_all_by_key(data, "channelExternalLinkViewModel")
        urls = []
        for entry in ext_entries:
            content = entry.get("link", {}).get("content", "")
            if content:
                if not content.startswith("http"):
                    content = "https://" + content
                if content not in urls:
                    urls.append(content)

        return urls[:15]
    except Exception:
        return []


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
                # Engagement Rate: avg_views / subscribers × 100
                # Measures: what % of subscribers actually watch each video
                eng_rate = round(avg_views / sub_count * 100, 2) if sub_count > 0 and avg_views > 0 else None

                description  = snippet.get("description", "")
                keywords_str = branding.get("keywords", "")
                combined     = f"{description} {keywords_str} {snippet.get('title', '')}"

                niche, niches = classify_niche(combined)

                # Build profile_url first — needed for channel About page scraping
                custom_url = snippet.get("customUrl", "")
                profile_url = (
                    f"https://www.youtube.com/{custom_url}"
                    if custom_url else
                    f"https://www.youtube.com/channel/{item['id']}"
                )

                email = extract_email(description)
                # Αν δεν βρέθηκε email, ψάξε στο Linktree/Beacons από bio
                if not email:
                    email = find_email_via_linkinbio(description)
                # Αν ακόμα δεν βρέθηκε, scrape channel About page για links
                if not email:
                    ext_links = scrape_youtube_channel_links(profile_url)
                    for ext_url in ext_links:
                        # Ψάξε email στο κάθε εξωτερικό link
                        scraped = find_email_via_linkinbio(ext_url) or scrape_generic(ext_url)
                        if scraped:
                            email = scraped
                            break

                results.append({
                    "platform":        "youtube",
                    "platform_id":     item["id"],
                    "username":        (custom_url or item["id"]).lstrip("@"),
                    "display_name":    snippet.get("title", ""),
                    "followers":       sub_count,
                    "following":       None,
                    "posts_count":     video_count,
                    "avg_views":       avg_views,
                    "engagement_rate": eng_rate,
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
        max_per_query: int = 50,
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
