# bot/link_preview.py
"""
Link understanding — fetch meta tags from shared URLs.

When someone shares a link, the bot fetches the page title, description,
and og:* tags so it can comment intelligently on the content — like a
real person who clicks links before replying.
"""

import logging
import os
import re
import random

import httpx

logger = logging.getLogger(__name__)

LINK_REACT_CHANCE = float(os.getenv("LINK_REACT_CHANCE", "0.55"))

# Regex to extract URLs from text
_URL_RE = re.compile(
    r"https?://[^\s\])'\">,]+"
    , re.IGNORECASE
)

# Meta tag patterns
_META_PATTERNS = {
    "og:title":       re.compile(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']', re.IGNORECASE),
    "og:description": re.compile(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']', re.IGNORECASE),
    "og:site_name":   re.compile(r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\'](.*?)["\']', re.IGNORECASE),
    "title":          re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL),
    "description":    re.compile(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', re.IGNORECASE),
}

# Also try reversed attribute order (content before property)
_META_PATTERNS_REV = {
    "og:title":       re.compile(r'<meta[^>]+content=["\'](.*?)["\'][^>]+property=["\']og:title["\']', re.IGNORECASE),
    "og:description": re.compile(r'<meta[^>]+content=["\'](.*?)["\'][^>]+property=["\']og:description["\']', re.IGNORECASE),
    "description":    re.compile(r'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']description["\']', re.IGNORECASE),
}


def extract_links(text: str) -> list[str]:
    """Return all HTTP/HTTPS URLs found in text."""
    return _URL_RE.findall(text)


def should_react_to_link(mentioned: bool = False) -> bool:
    """Decide whether to fetch and comment on a link."""
    if mentioned:
        return True  # always fetch if bot is tagged alongside a link
    return random.random() < LINK_REACT_CHANCE


async def fetch_link_metadata(url: str) -> dict[str, str]:
    """
    Fetch a URL and extract key metadata.

    Returns dict with keys: title, description, site_name, url, transcript.
    All values are strings (empty string if not found).
    For YouTube URLs, also fetches the video transcript when available.
    """
    result = {"title": "", "description": "", "site_name": "", "url": url, "transcript": ""}

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; TelegramBot/1.0; +https://core.telegram.org/bots)"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "az,en;q=0.9",
    }

    try:
        async with httpx.AsyncClient(
            timeout=8,
            follow_redirects=True,
            headers=headers,
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()

            # Only process HTML responses
            ct = resp.headers.get("content-type", "")
            if "html" not in ct:
                return result

            # Read first 50KB — enough for meta tags, skip huge pages
            html = resp.text[:50_000]

    except Exception as e:
        logger.debug("Link fetch failed for %s: %s", url, e)
        return result

    # Extract meta values — try both attribute orders
    for key, pattern in _META_PATTERNS.items():
        m = pattern.search(html)
        if not m:
            m = _META_PATTERNS_REV.get(key, re.compile("$")).search(html)
        if m:
            val = m.group(1).strip()
            # Decode common HTML entities
            val = val.replace("&amp;", "&").replace("&lt;", "<").replace(
                "&gt;", ">").replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
            # Map meta keys to result keys
            if key in ("og:title", "title") and not result["title"]:
                result["title"] = val[:200]
            elif key in ("og:description", "description") and not result["description"]:
                result["description"] = val[:400]
            elif key == "og:site_name":
                result["site_name"] = val[:100]

    # For YouTube links, also fetch the transcript
    from bot.youtube_utils import extract_video_id, get_youtube_transcript
    if extract_video_id(url):
        transcript = await get_youtube_transcript(url)
        if transcript:
            result["transcript"] = transcript

    return result


def format_link_context(metadata: dict[str, str]) -> str:
    """Format fetched metadata into a context hint for the AI."""
    parts = []
    if metadata["site_name"]:
        parts.append(f"Sayt: {metadata['site_name']}")
    if metadata["title"]:
        parts.append(f"Başlıq: {metadata['title']}")
    if metadata["description"]:
        desc = metadata["description"]
        if len(desc) > 200:
            desc = desc[:200] + "..."
        parts.append(f"Açıqlama: {desc}")
    if metadata.get("transcript"):
        snippet = metadata["transcript"][:400]
        if len(metadata["transcript"]) > 400:
            snippet += "..."
        parts.append(f"Video mətni: {snippet}")
    if not parts:
        parts.append(f"Link: {metadata['url']}")
    return "\n".join(parts)
