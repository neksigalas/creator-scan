"""
Link-in-bio email scraper.
Ανιχνεύει Linktree, Beacons, bio.link, allmylinks, campsite, κτλ.
από το bio ενός creator και βρίσκει κρυμμένα emails.

Χωρίς Playwright — μόνο requests (γρήγορο, χωρίς headless overhead).
"""
import json
import re
import time
from typing import Optional

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# URL patterns που ψάχνουμε στο bio
LINKINBIO_PATTERNS = [
    # Linktree variants
    (r"linktr\.ee/[\w\.\-_]+",              "linktree"),
    (r"linktree\.ee/[\w\.\-_]+",            "linktree"),
    # Beacons
    (r"beacons\.ai/[\w\.\-_]+",             "beacons"),
    (r"beacons\.page/[\w\.\-_]+",           "beacons"),
    # Bio.link
    (r"bio\.link/[\w\.\-_]+",               "biolink"),
    # Allmylinks
    (r"allmylinks\.com/[\w\.\-_]+",         "allmylinks"),
    # Campsite
    (r"campsite\.bio/[\w\.\-_]+",           "campsite"),
    # Carrd
    (r"[\w\-]+\.carrd\.co",                 "carrd"),
    # Later
    (r"later\.com/[@\w\.\-_]+",             "later"),
    # Milkshake
    (r"milkshake\.app/[\w\.\-_]+",          "milkshake"),
    # Snipfeed
    (r"snipfeed\.co/[\w\.\-_]+",            "snipfeed"),
    # Koji
    (r"koji\.com/[\w\.\-_]+",               "koji"),
    # Taplink
    (r"taplink\.cc/[\w\.\-_]+",             "taplink"),
    # Solo.to
    (r"solo\.to/[\w\.\-_]+",                "soloto"),
    # Generic: any URL in bio (fallback)
]

EMAIL_PATTERN = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
)


def extract_linkinbio_url(text: str) -> tuple[Optional[str], str]:
    """
    Εξάγει την πρώτη link-in-bio URL από το bio text.
    Επιστρέφει (full_url, service_name) ή (None, '').
    """
    if not text:
        return None, ""

    for pattern, service in LINKINBIO_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            url = m.group(0)
            if not url.startswith("http"):
                url = "https://" + url
            return url, service

    return None, ""


def scrape_linktree(url: str) -> Optional[str]:
    """
    Scrapes Linktree page. Linktree uses Next.js —
    data is in <script id="__NEXT_DATA__"> JSON.
    Ψάχνει για mailto: links ή email text.
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        html = resp.text

        # 1. Check for Next.js data
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>', html, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                # Walk JSON looking for mailto: or email strings
                text_blob = json.dumps(data)
                em = EMAIL_PATTERN.search(text_blob)
                if em:
                    return em.group(0)
                # Also check for mailto: href
                mailto = re.search(r'mailto:([^\s\\"&<>]+)', text_blob)
                if mailto:
                    return mailto.group(1)
            except json.JSONDecodeError:
                pass

        # 2. Fallback: scan raw HTML
        mailto = re.search(r'mailto:([^\s"&<>]+)', html)
        if mailto:
            return mailto.group(1)

        em = EMAIL_PATTERN.search(html)
        if em:
            return em.group(0)

    except Exception:
        pass
    return None


def scrape_beacons(url: str) -> Optional[str]:
    """Scrapes Beacons.ai page for email."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        html = resp.text

        # Beacons embeds data in window.__beacons_data__ or __NEXT_DATA__
        for pattern in [
            r'window\.__beacons_data__\s*=\s*({.+?});',
            r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>',
        ]:
            m = re.search(pattern, html, re.DOTALL)
            if m:
                try:
                    blob = json.loads(m.group(1))
                    text = json.dumps(blob)
                    em = EMAIL_PATTERN.search(text)
                    if em:
                        return em.group(0)
                    mailto = re.search(r'mailto:([^\s\\"&<>]+)', text)
                    if mailto:
                        return mailto.group(1)
                except Exception:
                    pass

        # Fallback
        mailto = re.search(r'mailto:([^\s"&<>]+)', html)
        if mailto:
            return mailto.group(1)

    except Exception:
        pass
    return None


def scrape_generic(url: str) -> Optional[str]:
    """Generic scraper — ψάχνει mailto: και email text σε οποιαδήποτε σελίδα."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        html = resp.text

        # mailto: links πρώτα (πιο αξιόπιστα)
        mailto = re.search(r'mailto:([^\s"&<>]+)', html)
        if mailto:
            return mailto.group(1)

        # Email pattern στο HTML
        em = EMAIL_PATTERN.search(html)
        if em:
            e = em.group(0)
            # Αποφύγετε false positives (π.χ. .png, .jpg domain endings)
            if not any(e.endswith(x) for x in ['.png', '.jpg', '.gif', '.svg', '.js', '.css']):
                return e

    except Exception:
        pass
    return None


SCRAPERS = {
    "linktree":   scrape_linktree,
    "beacons":    scrape_beacons,
    "biolink":    scrape_generic,
    "allmylinks": scrape_generic,
    "campsite":   scrape_generic,
    "carrd":      scrape_generic,
    "later":      scrape_generic,
    "milkshake":  scrape_generic,
    "snipfeed":   scrape_generic,
    "koji":       scrape_generic,
    "taplink":    scrape_generic,
    "soloto":     scrape_generic,
}


def find_email_via_linkinbio(bio: str) -> Optional[str]:
    """
    Main function: δίνεις bio text, επιστρέφει email ή None.
    Ανιχνεύει URL → scrapes → επιστρέφει email.
    """
    if not bio:
        return None

    url, service = extract_linkinbio_url(bio)
    if not url:
        return None

    scraper = SCRAPERS.get(service, scrape_generic)
    email = scraper(url)

    # Βασική sanity check
    if email and "@" in email and "." in email.split("@")[-1]:
        return email.strip().lower()

    return None
