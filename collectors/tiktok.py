"""
TikTok collector — Playwright-based, ZERO API cost, no login needed.

Στρατηγική:
  1. Playwright ανοίγει TikTok search page
  2. page.evaluate() διαβάζει window.__UNIVERSAL_DATA_FOR_REHYDRATION__ (JS object)
  3. Walk JSON → εξάγει users με follower counts
  4. Fallback: intercept /api/search/user/full/ XHR

Δεν χρειάζεται API key ή login.
"""

import json
import time
import random
from typing import Generator

from rich.console import Console

from processors.niche import classify_niche, extract_email

console = Console()

NICHE_QUERIES: dict[str, list[str]] = {
    "Gaming":       ["gaming creator", "gamer", "esports"],
    "Fitness":      ["fitness coach", "workout", "gym motivation"],
    "Tech":         ["tech reviewer", "coding", "software dev"],
    "Beauty":       ["makeup artist", "skincare", "beauty tips"],
    "Food":         ["food creator", "cooking recipes", "foodie"],
    "Travel":       ["travel creator", "travel vlog", "nomad"],
    "Finance":      ["finance tips", "investing", "money tips"],
    "Education":    ["educational content", "learn online", "tutorial"],
    "Fashion":      ["fashion creator", "outfit ideas", "style"],
    "Music":        ["musician", "singer", "music artist"],
    "Art & Design": ["artist", "digital art", "illustration"],
    "Comedy":       ["comedy creator", "funny videos", "humor"],
    "Lifestyle":    ["lifestyle creator", "daily vlog", "wellness"],
    "Parenting":    ["parenting tips", "mom tiktok", "family"],
    "DIY & Crafts": ["diy projects", "crafts tutorial", "handmade"],
    "Sports":       ["sports creator", "athlete", "training"],
    "Pets & Animals": ["pet creator", "dog tiktok", "cat videos"],
    "Business":     ["entrepreneur", "business tips", "startup"],
}

STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
window.chrome = {runtime: {}};
"""

EXTRACT_USERS_JS = """
() => {
    const data = window['__UNIVERSAL_DATA_FOR_REHYDRATION__'];
    if (!data) return [];

    const users = [];

    function walk(obj, depth) {
        if (!obj || typeof obj !== 'object' || depth > 12) return;

        // Check if this looks like a TikTok user object
        if ((obj.followerCount !== undefined || obj.follower_count !== undefined) &&
            (obj.uniqueId || obj.unique_id || obj.id)) {
            users.push({
                uid: String(obj.id || obj.uid || obj.uniqueId || ''),
                uniqueId: obj.uniqueId || obj.unique_id || '',
                nickname: obj.nickname || '',
                followerCount: obj.followerCount || obj.follower_count || 0,
                followingCount: obj.followingCount || obj.following_count || 0,
                videoCount: obj.videoCount || obj.aweme_count || 0,
                signature: obj.signature || obj.bio || '',
                avatarUrl: (obj.avatarMedium && obj.avatarMedium.urlList && obj.avatarMedium.urlList[0]) ||
                           (obj.avatar_medium && obj.avatar_medium.url_list && obj.avatar_medium.url_list[0]) ||
                           obj.avatarUrl || '',
                region: obj.region || '',
            });
            return;
        }

        if (Array.isArray(obj)) {
            for (const item of obj) walk(item, depth + 1);
        } else {
            for (const key of Object.keys(obj)) {
                walk(obj[key], depth + 1);
            }
        }
    }

    walk(data, 0);
    return users;
}
"""


def _get_playwright():
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except ImportError:
        raise ImportError(
            "Playwright δεν είναι installed.\n"
            "Τρέξε: pip install playwright && playwright install chromium"
        )


class TikTokCollector:
    """
    Scrapes TikTok χωρίς API key.
    Χρησιμοποιεί Playwright headless Chromium + JS global extraction.
    """

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._sync_playwright = _get_playwright()

    def _search_users(self, query: str, max_results: int = 30) -> list[dict]:
        """
        Ανοίγει TikTok search → route intercept για /api/search/user/full/ JSON.
        Χρησιμοποιεί route.fetch() για αξιόπιστη πρόσβαση στο response body.
        """
        xhr_results: list[dict] = []

        with self._sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.headless,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            ctx = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1440, "height": 900},
                locale="en-US",
            )

            page = ctx.new_page()

            # ⚠ Critical: read body() INLINE in the handler (NOT after storing the object)
            def on_resp(response):
                if "search/user/full" in response.url:
                    try:
                        raw = response.body()
                        if not raw:
                            return
                        body = json.loads(raw.decode("utf-8", errors="replace"))
                        for u in (body.get("user_list") or body.get("userList") or []):
                            info = u.get("user_info") or u.get("userInfo") or u
                            if info:
                                xhr_results.append(info)
                    except Exception:
                        pass

            page.on("response", on_resp)

            try:
                url = f"https://www.tiktok.com/search/user?q={query.replace(' ', '+')}"
                page.goto(url, wait_until="networkidle", timeout=35_000)
                time.sleep(random.uniform(2, 3))

                # Scroll to trigger more results
                for _ in range(2):
                    page.mouse.wheel(0, random.randint(400, 700))
                    time.sleep(random.uniform(0.8, 1.5))

            except Exception as e:
                console.print(f"    [yellow]⚠ TikTok nav error: {e}[/yellow]")
            finally:
                browser.close()

        return xhr_results[:max_results]

    def scan_niche(
        self,
        niche: str,
        min_followers: int = 2_000,
        max_followers: int = 100_000,
        max_per_query: int = 20,
    ) -> Generator[dict, None, None]:
        """Σκανάρει TikTok για μια niche."""
        queries = NICHE_QUERIES.get(niche, [niche])
        seen_ids: set[str] = set()

        for query in queries[:3]:
            console.print(f"  🎵 TikTok search: [cyan]{query}[/cyan]")
            try:
                raw_users = self._search_users(query, max_results=max_per_query)
            except Exception as e:
                console.print(f"    [red]✗ Error: {e}[/red]")
                continue

            if not raw_users:
                console.print(f"    [dim]0 αποτελέσματα για '{query}'[/dim]")
                continue

            console.print(f"    [dim]→ {len(raw_users)} raw users[/dim]")

            for info in raw_users:
                uid = str(
                    info.get("uid") or info.get("id") or
                    info.get("uniqueId") or info.get("unique_id") or ""
                )
                if not uid or uid in seen_ids:
                    continue
                seen_ids.add(uid)

                followers = int(
                    info.get("followerCount") or
                    info.get("follower_count") or 0
                )
                if not (min_followers <= followers <= max_followers):
                    continue

                username = (
                    info.get("uniqueId") or info.get("unique_id") or
                    info.get("sec_uid") or uid
                )
                nickname   = info.get("nickname") or username
                bio        = info.get("signature") or ""
                avatar_url = info.get("avatarUrl") or ""

                if not avatar_url:
                    av = info.get("avatarMedium") or info.get("avatar_medium") or {}
                    if isinstance(av, dict):
                        urls = av.get("urlList") or av.get("url_list") or []
                        avatar_url = urls[0] if urls else ""
                    elif isinstance(av, str):
                        avatar_url = av

                primary_niche, niches = classify_niche(f"{bio} {nickname} {username}")
                if niche not in niches:
                    niches.insert(0, niche)
                email = extract_email(bio)

                yield {
                    "platform":        "tiktok",
                    "platform_id":     uid,
                    "username":        username,
                    "display_name":    nickname,
                    "followers":       followers,
                    "following":       int(info.get("followingCount") or info.get("following_count") or 0),
                    "posts_count":     int(info.get("videoCount") or info.get("aweme_count") or 0),
                    "avg_views":       None,
                    "engagement_rate": None,
                    "niche":           primary_niche,
                    "niches":          niches[:3],
                    "language":        None,
                    "country":         info.get("region") or None,
                    "bio":             bio[:1000],
                    "profile_url":     f"https://www.tiktok.com/@{username}",
                    "avatar_url":      avatar_url,
                    "email":           email,
                    "has_email":       1 if email else 0,
                    "tags":            [],
                }

            time.sleep(random.uniform(1.5, 3))
