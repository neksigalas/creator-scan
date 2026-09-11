"""
Instagram collector — dual-strategy:

  Strategy A (login): instaloader hashtag search (best results)
    Set IG_USERNAME + IG_PASSWORD env vars → automatic login

  Strategy B (no-login): Google → site:instagram.com queries
    Extracts usernames from search results, then instaloader fetches profiles.

Both strategies feed the same profile-parse pipeline.
"""

import os
import re
import time
import random
import logging
from typing import Generator

import instaloader
import requests
from rich.console import Console

from processors.niche import classify_niche, extract_email
from processors.linktree import find_email_via_linkinbio

console = Console()
logging.getLogger("instaloader").setLevel(logging.ERROR)

# Google search headers (rotate to stay under radar)
GOOGLE_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

# ── Niche → (Google keywords, hashtags) ───────────────────────────────────────
NICHE_CONFIG: dict[str, dict] = {
    "Gaming": {
        "google": ["gaming creator instagram", "small gaming youtuber instagram",
                   "indie game streamer instagram", "retro gaming instagram"],
        "hashtags": ["smallgamingchannel", "indiegamer", "pcgamer", "gamingyoutuber",
                     "retrogaming", "cozystreamer"],
    },
    "Fitness": {
        "google": ["fitness content creator instagram", "personal trainer instagram creator",
                   "home workout creator instagram", "small fitness influencer"],
        "hashtags": ["fitnesscreator", "fitnessjourney", "homeworkout", "personaltrainerlife"],
    },
    "Tech": {
        "google": ["tech reviewer instagram", "gadget reviewer instagram creator",
                   "coding content creator instagram", "small tech influencer"],
        "hashtags": ["techcreator", "techreviewer", "codinglife", "developerlife"],
    },
    "Beauty": {
        "google": ["beauty content creator instagram", "makeup tutorial instagram creator",
                   "skincare creator instagram", "small beauty influencer instagram"],
        "hashtags": ["beautycontentcreator", "makeuptutorial", "skincareroutine"],
    },
    "Food": {
        "google": ["food content creator instagram", "recipe creator instagram",
                   "cooking channel instagram", "small food influencer"],
        "hashtags": ["foodcontentcreator", "foodblogger", "recipecreator", "homecooking"],
    },
    "Travel": {
        "google": ["travel content creator instagram", "budget travel blogger instagram",
                   "digital nomad instagram creator", "solo travel instagram"],
        "hashtags": ["travelblogger", "travelcreator", "digitalnomadlife", "solotravel"],
    },
    "Finance": {
        "google": ["personal finance creator instagram", "money tips instagram creator",
                   "investing content creator instagram", "financial freedom instagram"],
        "hashtags": ["financecreator", "personalfinance", "moneytips", "investingtips"],
    },
    "Education": {
        "google": ["education content creator instagram", "online teacher instagram",
                   "study tips creator instagram", "tutorial creator instagram"],
        "hashtags": ["educationcreator", "studywithme", "onlineteacher", "tutorialcreator"],
    },
    "Fashion": {
        "google": ["fashion content creator instagram", "style blogger instagram",
                   "sustainable fashion creator instagram", "small fashion influencer"],
        "hashtags": ["fashioncontentcreator", "outfitinspo", "fashionblogger"],
    },
    "Music": {
        "google": ["indie musician instagram", "singer songwriter instagram creator",
                   "music producer instagram", "independent artist instagram"],
        "hashtags": ["musiciansofinstagram", "indieartist", "singersongwriter", "musicproducer"],
    },
    "Art & Design": {
        "google": ["digital artist instagram creator", "illustrator instagram",
                   "procreate artist instagram", "small art creator instagram"],
        "hashtags": ["digitalartist", "illustrator", "procreateartist"],
    },
    "Comedy": {
        "google": ["comedy creator instagram", "skit creator instagram",
                   "funny content creator instagram", "humor creator instagram"],
        "hashtags": ["comedycreator", "skitcreator", "comedyskit"],
    },
    "Lifestyle": {
        "google": ["lifestyle creator instagram", "daily routine creator instagram",
                   "wellness content creator instagram", "slow living instagram"],
        "hashtags": ["lifestyleblogger", "wellnesscreator", "morningroutine"],
    },
    "Parenting": {
        "google": ["parenting content creator instagram", "mom creator instagram",
                   "dad creator instagram", "family content creator instagram"],
        "hashtags": ["momcreator", "dadcreator", "parentingcontent"],
    },
    "DIY & Crafts": {
        "google": ["DIY content creator instagram", "craft creator instagram",
                   "handmade creator instagram", "tutorial maker instagram"],
        "hashtags": ["diyprojects", "craftingcommunity", "diytutorial"],
    },
    "Sports": {
        "google": ["sports content creator instagram", "athlete creator instagram",
                   "training content instagram", "sport motivation creator"],
        "hashtags": ["athletecreator", "sportsmotivation", "trainingvideo"],
    },
    "Pets & Animals": {
        "google": ["pet content creator instagram", "dog content creator instagram",
                   "cat creator instagram", "animal creator instagram"],
        "hashtags": ["petcontentcreator", "dogsofinstagram", "catsofinstagram"],
    },
    "Business": {
        "google": ["business creator instagram", "entrepreneur content creator instagram",
                   "startup instagram creator", "side hustle creator instagram"],
        "hashtags": ["entrepreneurcreator", "businesstips", "startuplife", "solopreneur"],
    },
}

IG_USERNAME_RE = re.compile(
    r'(?:instagram\.com/|@)([A-Za-z0-9_.]{3,30})(?:/|\b)'
)


# ── Strategy B: Google → usernames ────────────────────────────────────────────
def _google_discover_usernames(query: str, max_results: int = 15) -> list[str]:
    """
    Searches Google for: site:instagram.com <query>
    Extracts Instagram usernames from result URLs.
    """
    search_url = (
        "https://www.google.com/search"
        f"?q=site%3Ainstagram.com+{requests.utils.quote(query)}"
        "&num=20&hl=en"
    )
    try:
        resp = requests.get(
            search_url,
            headers={"User-Agent": GOOGLE_UA},
            timeout=10,
        )
        if resp.status_code != 200:
            return []
        html = resp.text
        # Extract instagram usernames from URLs in the HTML
        found = IG_USERNAME_RE.findall(html)
        # Filter obvious non-profiles
        blacklist = {"accounts", "explore", "about", "press", "api", "help",
                     "legal", "privacy", "safety", "p", "reel", "reels",
                     "stories", "direct", "tv", "music", "shopping", "instagram"}
        usernames = []
        seen = set()
        for u in found:
            u_lower = u.lower()
            if u_lower not in blacklist and u not in seen and len(u) >= 4:
                seen.add(u)
                usernames.append(u)
        return usernames[:max_results]
    except Exception:
        return []


# ── Strategy A: instaloader hashtag (requires login) ─────────────────────────
def _hashtag_discover_usernames(
    L: instaloader.Instaloader,
    hashtag: str,
    max_results: int = 20,
) -> list[str]:
    """Discovers usernames from a hashtag's recent posts via instaloader."""
    usernames: list[str] = []
    try:
        tag = instaloader.Hashtag.from_name(L.context, hashtag)
        for post in tag.get_posts():
            if len(usernames) >= max_results:
                break
            usernames.append(post.owner_username)
            time.sleep(random.uniform(0.5, 1.0))
    except instaloader.exceptions.LoginRequiredException:
        pass  # caller handles this
    except Exception:
        pass
    return usernames


# ── Profile fetch + parse ─────────────────────────────────────────────────────
def _fetch_profile(L: instaloader.Instaloader, username: str) -> dict | None:
    """Fetch and parse one Instagram profile. Returns creator dict or None."""
    try:
        profile = instaloader.Profile.from_username(L.context, username)
    except instaloader.exceptions.ProfileNotExistsException:
        return None
    except instaloader.exceptions.LoginRequiredException:
        return None
    except Exception as e:
        if "429" in str(e) or "Too Many" in str(e):
            raise   # caller handles rate limit
        return None

    if profile.is_private:
        return None

    followers = profile.followers
    bio = profile.biography or ""

    # Email discovery
    email = extract_email(bio)
    if not email and profile.external_url:
        ext = profile.external_url or ""
        if any(k in ext for k in ["linktree", "linktr.ee", "beacons", "bio.link", "lnk.bio"]):
            email = find_email_via_linkinbio(bio)
        if not email:
            try:
                r = requests.get(ext, timeout=8, headers={"User-Agent": GOOGLE_UA})
                email = extract_email(r.text)
            except Exception:
                pass

    # Engagement rate from recent posts
    er = None
    try:
        posts = list(profile.get_posts())[:8]
        if posts and followers:
            avg_likes = sum(p.likes for p in posts) / len(posts)
            er = round((avg_likes / followers) * 100, 2)
    except Exception:
        pass

    # Niche classification
    niche_text = f"{bio} {profile.full_name or ''} {username}"
    primary_niche, niches = classify_niche(niche_text)

    return {
        "platform":        "instagram",
        "platform_id":     str(profile.userid),
        "username":        username,
        "display_name":    profile.full_name or username,
        "followers":       int(followers),
        "following":       int(profile.followees),
        "avg_views":       None,
        "engagement_rate": er,
        "niche":           primary_niche,
        "language":        None,
        "country":         None,
        "bio":             bio[:1000],
        "profile_url":     f"https://www.instagram.com/{username}/",
        "avatar_url":      profile.profile_pic_url or "",
        "email":           email,
        "has_email":       1 if email else 0,
        "tags":            [],
    }


# ── Main collect function ──────────────────────────────────────────────────────
def collect_instagram(
    niche: str,
    min_followers: int = 2_000,
    max_followers: int = 100_000,
    max_per_query: int = 20,
    sample_posts: int = 8,
) -> Generator[dict, None, None]:
    """
    Main entry point. Tries Strategy A (login+hashtags) first,
    falls back to Strategy B (Google) if no login is configured.
    """
    cfg = NICHE_CONFIG.get(niche, {
        "google": [f"{niche} content creator instagram"],
        "hashtags": [niche.lower().replace(" ", "")],
    })

    # Setup instaloader
    L = instaloader.Instaloader(
        download_pictures=False, download_videos=False,
        download_video_thumbnails=False, download_geotags=False,
        download_comments=False, save_metadata=False,
        compress_json=False, quiet=True,
        request_timeout=20, max_connection_attempts=2,
    )
    L.context.sleep_between_requests = 0

    # Try login if credentials are provided
    ig_user = os.getenv("IG_USERNAME")
    ig_pass = os.getenv("IG_PASSWORD")
    logged_in = False
    if ig_user and ig_pass:
        try:
            L.login(ig_user, ig_pass)
            logged_in = True
            console.print(f"  [green]✓ Instagram logged in as {ig_user}[/green]")
        except Exception as e:
            console.print(f"  [yellow]⚠ IG login failed: {e}[/yellow]")

    seen: set[str] = set()

    def _process_username(username: str):
        if username in seen:
            return
        seen.add(username)
        time.sleep(random.uniform(2.0, 4.0))
        try:
            creator = _fetch_profile(L, username)
        except Exception as e:
            if "429" in str(e) or "Too Many" in str(e):
                console.print("  [yellow]⚠ IG rate limited — pausing 60s[/yellow]")
                time.sleep(60)
            return
        if creator and (min_followers <= creator["followers"] <= max_followers):
            # Override niche with the one being scanned
            creator["niche"] = creator.get("niche") or niche
            return creator
        return None

    # ── Strategy A: Login + Hashtag search ──────────────────────────────────
    if logged_in:
        console.print("  [cyan]Using Strategy A: Login + Hashtag search[/cyan]")
        for tag in cfg["hashtags"][:4]:
            console.print(f"  📸 Instagram [cyan]#{tag}[/cyan]")
            usernames = _hashtag_discover_usernames(L, tag, max_results=max_per_query)
            if not usernames:
                console.print(f"  [yellow]⚠ No results for #{tag} (login may be needed)[/yellow]")
                continue
            for uname in usernames:
                result = _process_username(uname)
                if result:
                    yield result
            time.sleep(random.uniform(5, 10))
        return

    # ── Strategy B: Google → username discovery ──────────────────────────────
    console.print("  [cyan]Using Strategy B: Google search (no login)[/cyan]")
    console.print("  [dim]Tip: set IG_USERNAME + IG_PASSWORD env vars for more results[/dim]")

    for query in cfg["google"][:4]:
        console.print(f"  🔍 Google: [cyan]{query}[/cyan]")
        usernames = _google_discover_usernames(query, max_results=max_per_query)
        console.print(f"      Found {len(usernames)} usernames: {usernames[:3]}...")
        for uname in usernames:
            result = _process_username(uname)
            if result:
                yield result
        time.sleep(random.uniform(3, 7))


# ── Legacy class interface ────────────────────────────────────────────────────
class InstagramCollector:
    """Thin wrapper so main.py still works with `collector.scan_niche()`."""

    def __init__(self, headless: bool = True):
        pass

    def scan_niche(
        self,
        niche: str,
        min_followers: int = 2_000,
        max_followers: int = 100_000,
        max_per_query: int = 20,
        use_playwright: bool = False,
    ) -> Generator[dict, None, None]:
        yield from collect_instagram(
            niche=niche,
            min_followers=min_followers,
            max_followers=max_followers,
            max_per_query=max_per_query,
        )
