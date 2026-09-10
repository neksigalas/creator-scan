"""
Instagram collector — Playwright-based, ZERO API cost, no login needed.

Στρατηγική:
  1. Playwright ανοίγει Instagram hashtag explore page
  2. Intercepts XHR → /api/v1/users/web_profile_info/ JSON (έχει follower count)
  3. Φιλτράρει με follower range, yields creator dicts

Δεν χρειάζεται login ή API key.
"""

import json
import time
import random
import re
from typing import Generator

from rich.console import Console

from processors.niche import classify_niche, extract_email

console = Console()

IG_APP_ID = "936619743392459"

# Niche → Instagram hashtags to explore
NICHE_HASHTAGS: dict[str, list[str]] = {
    "Gaming":       ["gamer", "gamingcommunity", "esports", "pcgaming"],
    "Fitness":      ["fitnesscoach", "personaltrainer", "gymlife", "fitnessmotivation"],
    "Tech":         ["techreviewer", "coding", "programminglife", "softwaredeveloper"],
    "Beauty":       ["makeuptutorial", "beautyinfluencer", "skincareroutine", "mua"],
    "Food":         ["foodblogger", "foodphotography", "homecooking", "recipecreator"],
    "Travel":       ["travelblogger", "travelinfluencer", "digitalnomad", "wanderlust"],
    "Finance":      ["financetips", "personalfinance", "investingtips", "moneytips"],
    "Education":    ["educationcontent", "onlineteaching", "studytips", "elearning"],
    "Fashion":      ["fashionblogger", "outfitoftheday", "fashioninfluencer", "styleinspo"],
    "Music":        ["musicianlife", "indieartist", "singersongwriter", "musicproducer"],
    "Art & Design": ["digitalartist", "illustrationart", "artistsoninstagram", "digitalart"],
    "Comedy":       ["comedycreator", "funnyvideos", "standupcomedy", "memes"],
    "Lifestyle":    ["lifestyleblogger", "dailyroutine", "wellnessjourney", "selfcare"],
    "Parenting":    ["momblogger", "dadblog", "parentinglife", "familyblog"],
    "DIY & Crafts": ["diycrafts", "craftinglife", "handmade", "diytutorial"],
    "Sports":       ["sportslife", "athletelife", "sportsmotivation", "training"],
    "Pets & Animals": ["doginfluencer", "catlovers", "petlife", "animallovers"],
    "Business":     ["entrepreneurlife", "businesstips", "startuplife", "sidehustle"],
}


def _get_playwright():
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except ImportError:
        raise ImportError(
            "Playwright δεν είναι installed.\n"
            "Τρέξε: pip install playwright && playwright install chromium"
        )


class InstagramCollector:
    """
    Scrapes Instagram χωρίς API key/login.
    Playwright intercepts profile info XHR calls.
    """

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._sync_playwright = _get_playwright()

    def _get_usernames_from_hashtag(self, hashtag: str, max_results: int = 15) -> list[str]:
        """
        Ανοίγει Instagram hashtag page → intercepts API calls → εξάγει usernames.
        """
        usernames: list[str] = []

        with self._sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.headless,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
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

            def on_resp(response):
                url = response.url
                # Intercept explore/search/tagged feeds for usernames
                if any(k in url for k in ["tagged/", "explore/", "users/lookup", "topsearch"]):
                    try:
                        raw = response.body()
                        if not raw:
                            return
                        data = json.loads(raw.decode("utf-8", errors="replace"))
                        # Walk JSON for usernames
                        _extract_usernames(data, usernames, max_results)
                    except Exception:
                        pass

            page.on("response", on_resp)

            try:
                url = f"https://www.instagram.com/explore/tags/{hashtag}/"
                page.goto(url, wait_until="networkidle", timeout=30_000)
                time.sleep(random.uniform(1.5, 2.5))

                # Try to extract from page JavaScript state
                try:
                    found = page.evaluate("""() => {
                        const usernames = [];
                        const links = document.querySelectorAll('a[href*="/"]');
                        for (const link of links) {
                            const m = link.href.match(/instagram\\.com\\/([a-zA-Z0-9_.]{3,30})\\/$/);
                            if (m && !['explore','accounts','about','press','api','help'].includes(m[1])) {
                                usernames.push(m[1]);
                            }
                        }
                        return [...new Set(usernames)].slice(0, 20);
                    }""")
                    for u in (found or []):
                        if u not in usernames:
                            usernames.append(u)
                except Exception:
                    pass

            except Exception as e:
                console.print(f"    [yellow]⚠ IG hashtag error ({hashtag}): {e}[/yellow]")
            finally:
                browser.close()

        return usernames[:max_results]

    def _fetch_profiles(self, usernames: list[str]) -> list[dict]:
        """
        Για κάθε username, ανοίγει το Instagram profile και intercepts
        το /api/v1/users/web_profile_info/ XHR call (που περιέχει follower count).
        """
        profiles: list[dict] = []

        with self._sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.headless,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
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

            for username in usernames:
                profile_data: dict = {}

                def on_resp(response):
                    if "web_profile_info" in response.url:
                        try:
                            raw = response.body()
                            if not raw:
                                return
                            body = json.loads(raw.decode("utf-8", errors="replace"))
                            user = body.get("data", {}).get("user") or {}
                            if user:
                                profile_data.update(user)
                        except Exception:
                            pass

                page.on("response", on_resp)

                try:
                    page.goto(
                        f"https://www.instagram.com/{username}/",
                        wait_until="networkidle",
                        timeout=25_000,
                    )
                    time.sleep(random.uniform(1, 2))

                    # Fallback: read from page meta tags
                    if not profile_data:
                        try:
                            meta_desc = page.locator('meta[name="description"]').get_attribute("content") or ""
                            m_followers = re.search(r"([\d,.]+[KkMm]?)\s+Followers", meta_desc)
                            if m_followers:
                                raw_followers = m_followers.group(1).replace(",", "").replace(".", "")
                                mult = 1
                                if raw_followers.endswith(("K", "k")):
                                    mult = 1000
                                    raw_followers = raw_followers[:-1]
                                elif raw_followers.endswith(("M", "m")):
                                    mult = 1_000_000
                                    raw_followers = raw_followers[:-1]
                                profile_data["username"] = username
                                profile_data["_approx_followers"] = int(float(raw_followers) * mult)
                        except Exception:
                            pass

                    if profile_data:
                        profiles.append(profile_data)

                except Exception as e:
                    console.print(f"    [yellow]⚠ IG profile error ({username}): {e}[/yellow]")
                finally:
                    page.remove_listener("response", on_resp)

                time.sleep(random.uniform(1, 2))

            browser.close()

        return profiles

    def scan_niche(
        self,
        niche: str,
        min_followers: int = 2_000,
        max_followers: int = 100_000,
        max_per_query: int = 15,
        use_playwright: bool = True,
    ) -> Generator[dict, None, None]:
        """Σκανάρει Instagram για μια niche."""
        hashtags = NICHE_HASHTAGS.get(niche, [niche.lower().replace(" ", "")])
        all_usernames: list[str] = []
        seen: set[str] = set()

        # Step 1: Discover usernames from hashtags
        for tag in hashtags[:3]:
            console.print(f"  📸 Instagram hashtag: [cyan]#{tag}[/cyan]")
            for u in self._get_usernames_from_hashtag(tag, max_results=max_per_query):
                if u not in seen:
                    seen.add(u)
                    all_usernames.append(u)
            time.sleep(random.uniform(1, 2))

        if not all_usernames:
            console.print(f"  [yellow]⚠ Δεν βρέθηκαν usernames για {niche}[/yellow]")
            return

        console.print(f"  📊 Fetching {len(all_usernames)} profiles via Playwright...")
        raw_profiles = self._fetch_profiles(all_usernames[:max_per_query * 2])

        for profile in raw_profiles:
            creator = self._parse_profile(profile, niche)
            if creator and (min_followers <= creator["followers"] <= max_followers):
                yield creator

    def _parse_profile(self, profile: dict, fallback_niche: str) -> dict | None:
        """Raw IG profile → creator dict."""
        try:
            username = profile.get("username") or ""
            if not username:
                return None

            # Follower count: from web_profile_info or from meta fallback
            followers = (
                (profile.get("edge_followed_by") or {}).get("count") or
                profile.get("_approx_followers") or
                profile.get("follower_count") or 0
            )
            following = (
                (profile.get("edge_follow") or {}).get("count") or
                profile.get("following_count") or 0
            )
            posts = (
                (profile.get("edge_owner_to_timeline_media") or {}).get("count") or
                profile.get("media_count") or 0
            )

            bio = profile.get("biography") or ""
            display_name = profile.get("full_name") or username
            avatar = (
                profile.get("profile_pic_url_hd") or
                profile.get("profile_pic_url") or ""
            )

            # Engagement rate estimate
            er = None
            try:
                edges = (profile.get("edge_owner_to_timeline_media") or {}).get("edges", [])
                if edges and followers:
                    total = sum(
                        (e.get("node", {}).get("edge_liked_by", {}).get("count", 0) +
                         e.get("node", {}).get("edge_media_to_comment", {}).get("count", 0))
                        for e in edges[:12]
                    )
                    er = round((total / len(edges[:12]) / followers) * 100, 2)
            except Exception:
                pass

            primary_niche, niches = classify_niche(f"{bio} {display_name} {username}")
            if fallback_niche not in niches:
                niches.insert(0, fallback_niche)
            email = extract_email(bio)

            return {
                "platform":        "instagram",
                "platform_id":     profile.get("id") or username,
                "username":        username,
                "display_name":    display_name,
                "followers":       int(followers),
                "following":       int(following),
                "posts_count":     int(posts),
                "avg_views":       None,
                "engagement_rate": er,
                "niche":           primary_niche,
                "niches":          niches[:3],
                "language":        None,
                "country":         None,
                "bio":             bio[:1000],
                "profile_url":     f"https://www.instagram.com/{username}/",
                "avatar_url":      avatar,
                "email":           email,
                "has_email":       1 if email else 0,
                "tags":            [],
            }
        except Exception as e:
            console.print(f"    [yellow]⚠ parse_profile error: {e}[/yellow]")
            return None


def _extract_usernames(obj, result: list, max_results: int, depth: int = 0):
    """Walk JSON to find Instagram usernames."""
    if depth > 8 or len(result) >= max_results:
        return
    if isinstance(obj, dict):
        uname = obj.get("username")
        if uname and isinstance(uname, str) and len(uname) >= 3:
            if uname not in result:
                result.append(uname)
        for v in obj.values():
            _extract_usernames(v, result, max_results, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            _extract_usernames(item, result, max_results, depth + 1)
