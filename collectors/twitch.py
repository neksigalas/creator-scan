"""
Twitch Helix API collector.
Πλήρως δωρεάν — χωρίς quota limits (rate limited μόνο αν κάνεις spam).
Docs: https://dev.twitch.tv/docs/api/
"""
import os
import time
from typing import Generator

import requests
from rich.console import Console

from processors.niche import classify_niche, extract_email
from processors.linktree import find_email_via_linkinbio

console = Console()

TWITCH_AUTH_URL = "https://id.twitch.tv/oauth2/token"
TWITCH_API_BASE = "https://api.twitch.tv/helix"

# Twitch game categories → CreatorScan niches
CATEGORY_NICHE_MAP: dict[str, str] = {
    "Just Chatting":        "Lifestyle",
    "Art":                  "Art & Design",
    "Music":                "Music",
    "Fitness & Health":     "Fitness",
    "Food & Drink":         "Food",
    "Science & Technology": "Tech",
    "Travel & Outdoors":    "Travel",
    "Sports":               "Sports",
    "Beauty & Body Art":    "Beauty",
    "Talk Shows & Podcasts": "Education",
    "Minecraft":            "Gaming",
    "Fortnite":             "Gaming",
    "League of Legends":    "Gaming",
    "Valorant":             "Gaming",
    "Grand Theft Auto V":   "Gaming",
    "Apex Legends":         "Gaming",
    "Counter-Strike 2":     "Gaming",
    "World of Warcraft":    "Gaming",
    "Dota 2":               "Gaming",
    "Overwatch 2":          "Gaming",
    "Poker":                "Finance",
    "Crypto":               "Finance",
    "Chess":                "Education",
    "ASMR":                 "Lifestyle",
    "Slots":                "Finance",
}

# Niche → Twitch category names to search
NICHE_CATEGORIES: dict[str, list[str]] = {
    "Gaming":       [
        "Minecraft", "Fortnite", "Valorant", "Grand Theft Auto V", "Apex Legends",
        "League of Legends", "Counter-Strike 2", "Dota 2", "Overwatch 2",
        "Elden Ring", "Stardew Valley", "Rust", "Escape from Tarkov",
        "Hearthstone", "Magic: The Gathering Arena", "Teamfight Tactics",
        "Dead by Daylight", "Phasmophobia", "Among Us", "Fall Guys",
    ],
    "Fitness":      ["Fitness & Health"],
    "Tech":         ["Science & Technology", "Software and Game Development"],
    "Beauty":       ["Beauty & Body Art", "Makeup"],
    "Food":         ["Food & Drink", "Cooking"],
    "Travel":       ["Travel & Outdoors"],
    "Finance":      ["Poker", "Crypto", "Business & Finance"],
    "Education":    ["Talk Shows & Podcasts", "Chess", "Special Events", "Education"],
    "Music":        ["Music", "Makers & Crafting"],
    "Art & Design": ["Art", "3D Art", "Pixel Art", "Drawing"],
    "Lifestyle":    ["Just Chatting", "ASMR", "Pools, Hot Tubs, and Beaches"],
    "Sports":       ["Sports", "Boxing", "Basketball", "Football", "Soccer", "Tennis", "Golf"],
    "Comedy":       ["Just Chatting", "Talk Shows & Podcasts"],
    "Parenting":    ["Just Chatting"],
    "DIY & Crafts": ["Makers & Crafting", "Art"],
    "Pets & Animals": ["Animals, Aquariums, and Zoos"],
    "Business":     ["Business & Finance", "Entrepreneurship"],
}


class TwitchCollector:
    def __init__(self, client_id: str, client_secret: str):
        if not client_id or not client_secret:
            raise ValueError("Twitch Client ID και Secret απαιτούνται!")
        self.client_id = client_id
        self.client_secret = client_secret
        self._token: str | None = None

    def _get_token(self) -> str:
        """App Access Token (δωρεάν, ανανεώνεται αυτόματα)."""
        if self._token:
            return self._token
        resp = requests.post(TWITCH_AUTH_URL, params={
            "client_id":     self.client_id,
            "client_secret": self.client_secret,
            "grant_type":    "client_credentials",
        }, timeout=10)
        resp.raise_for_status()
        self._token = resp.json()["access_token"]
        return self._token

    def _headers(self) -> dict:
        return {
            "Client-Id":     self.client_id,
            "Authorization": f"Bearer {self._get_token()}",
        }

    def _get(self, endpoint: str, params: dict = None) -> dict:
        url = f"{TWITCH_API_BASE}/{endpoint}"
        resp = requests.get(url, headers=self._headers(), params=params, timeout=15)
        if resp.status_code == 401:
            self._token = None  # reset token
            resp = requests.get(url, headers=self._headers(), params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def get_game_id(self, game_name: str) -> str | None:
        """Βρίσκει το Twitch game_id από το όνομα."""
        data = self._get("games", {"name": game_name})
        items = data.get("data", [])
        return items[0]["id"] if items else None

    def get_streams_by_game(
        self,
        game_id: str,
        max_results: int = 100,
    ) -> list[dict]:
        """
        Παίρνει live streams για ένα game.
        Streams = active channels → πάμε μετά να πάρουμε followers.
        """
        streams = []
        cursor = None

        while len(streams) < max_results:
            params = {"game_id": game_id, "first": min(100, max_results - len(streams))}
            if cursor:
                params["after"] = cursor

            data = self._get("streams", params)
            batch = data.get("data", [])
            streams.extend(batch)

            cursor = data.get("pagination", {}).get("cursor")
            if not cursor or not batch:
                break
            time.sleep(0.2)

        return streams

    def get_channels_by_query(
        self,
        query: str,
        max_results: int = 100,
        live_only: bool = False,
    ) -> list[dict]:
        """Αναζητά channels με keyword."""
        channels = []
        cursor = None

        while len(channels) < max_results:
            params = {
                "query":      query,
                "first":      min(100, max_results - len(channels)),
                "live_only":  str(live_only).lower(),
            }
            if cursor:
                params["after"] = cursor

            data = self._get("search/channels", params)
            batch = data.get("data", [])
            channels.extend(batch)

            cursor = data.get("pagination", {}).get("cursor")
            if not cursor or not batch:
                break
            time.sleep(0.2)

        return channels

    def get_follower_counts(self, broadcaster_ids: list[str]) -> dict[str, int]:
        """
        Παίρνει follower count για κάθε broadcaster.
        Twitch Helix: GET /helix/channels/followers?broadcaster_id=X
        """
        counts = {}
        for bid in broadcaster_ids:
            try:
                data = self._get("channels/followers", {"broadcaster_id": bid, "first": 1})
                counts[bid] = data.get("total", 0)
            except Exception:
                counts[bid] = 0
            time.sleep(0.1)  # polite
        return counts

    def get_channel_info(self, broadcaster_ids: list[str]) -> list[dict]:
        """Παίρνει channel info (description, language) για batch IDs."""
        if not broadcaster_ids:
            return []
        results = []
        # Max 100 per request
        for i in range(0, len(broadcaster_ids), 100):
            batch = broadcaster_ids[i : i + 100]
            params = [("broadcaster_id", bid) for bid in batch]
            resp = requests.get(
                f"{TWITCH_API_BASE}/channels",
                headers=self._headers(),
                params=params,
                timeout=15,
            )
            if resp.ok:
                results.extend(resp.json().get("data", []))
            time.sleep(0.2)
        return results

    def scan_niche(
        self,
        niche: str,
        min_followers: int = 2_000,
        max_followers: int = 100_000,
        max_per_category: int = 40,  # μειώθηκε για speed (40×0.1s = 4s per category)
    ) -> Generator[dict, None, None]:
        """
        Σκανάρει μια niche στο Twitch.
        Ψάχνει live streams + channel search.
        """
        categories = NICHE_CATEGORIES.get(niche, [niche])

        for cat_name in categories:
            console.print(f"  🎮 Twitch category: [cyan]{cat_name}[/cyan]")

            # Μέθοδος 1: Streams by game
            game_id = self.get_game_id(cat_name)
            broadcaster_ids: list[str] = []

            if game_id:
                streams = self.get_streams_by_game(game_id, max_results=max_per_category)
                broadcaster_ids = [s["user_id"] for s in streams]

            # Μέθοδος 2: Channel search
            channels = self.get_channels_by_query(cat_name, max_results=max_per_category)
            for ch in channels:
                bid = ch.get("id")
                if bid and bid not in broadcaster_ids:
                    broadcaster_ids.append(bid)

            if not broadcaster_ids:
                continue

            # Πάρε follower counts
            console.print(f"    📊 Fetching followers για {len(broadcaster_ids)} channels...")
            follower_map = self.get_follower_counts(broadcaster_ids)

            # Φιλτράρισμα κατά range
            valid_ids = [
                bid for bid, cnt in follower_map.items()
                if min_followers <= cnt <= max_followers
            ]

            if not valid_ids:
                continue

            # Channel details
            channel_infos = self.get_channel_info(valid_ids)
            info_map = {ci["broadcaster_id"]: ci for ci in channel_infos}

            # Merge streams info
            streams_map: dict[str, dict] = {}
            for s in (streams if game_id else []):
                streams_map[s["user_id"]] = s
            for ch in channels:
                if ch.get("id"):
                    streams_map[ch["id"]] = streams_map.get(ch["id"], ch)

            for bid in valid_ids:
                s = streams_map.get(bid, {})
                info = info_map.get(bid, {})
                followers = follower_map[bid]

                display_name = (
                    s.get("user_name") or
                    info.get("broadcaster_name") or
                    s.get("display_name") or
                    bid
                )
                login = (
                    s.get("user_login") or
                    info.get("broadcaster_login") or
                    display_name.lower()
                )
                description = info.get("description") or s.get("title") or ""
                language = info.get("broadcaster_language") or s.get("language", "")
                game_used = info.get("game_name") or s.get("game_name") or cat_name

                # Map category to niche
                mapped_niche = CATEGORY_NICHE_MAP.get(game_used, niche)
                _, niches = classify_niche(
                    f"{description} {game_used} {display_name}"
                )
                if mapped_niche not in niches:
                    niches.insert(0, mapped_niche)

                email = extract_email(description)
                if not email:
                    email = find_email_via_linkinbio(description)

                live_viewers = int(s.get("viewer_count", 0))
                # Engagement Rate: live viewers / followers × 100
                # Measures: what % of followers are watching live concurrently
                tw_eng = round(live_viewers / followers * 100, 2) if followers > 0 and live_viewers > 0 else None

                yield {
                    "platform":        "twitch",
                    "platform_id":     bid,
                    "username":        login,
                    "display_name":    display_name,
                    "followers":       followers,
                    "following":       None,
                    "posts_count":     None,
                    "avg_views":       live_viewers,
                    "engagement_rate": tw_eng,
                    "niche":           mapped_niche,
                    "niches":          niches[:3],
                    "language":        language,
                    "country":         None,
                    "bio":             description[:1000],
                    "profile_url":     f"https://www.twitch.tv/{login}",
                    "avatar_url":      s.get("thumbnail_url", ""),
                    "email":           email,
                    "has_email":       1 if email else 0,
                    "tags":            (s.get("tags") or [])[:10],
                }
