"""
discovery/directory_extractor.py
=================================
Mines outbound company profile links from directory and listing pages
(Clutch, GoodFirms, LinkedIn companies, generic /company/ paths).

Instead of discarding DIRECTORY_LIST pages, the pipeline calls this
module to extract individual company profile URLs, which are then
re-queued for semantic evaluation.

Design decisions
----------------
- Hard cap of MAX_LINKS_PER_DIRECTORY (default 50) to prevent runaway crawling.
- Returns only absolute, deduplicated URLs.
- Platform-specific patterns take priority over the generic fallback.
- Social/media/app-store URLs are filtered out immediately.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

MAX_LINKS_PER_DIRECTORY = 50


def _is_valid_url(url: str) -> bool:
    if not url:
        return False
    url = url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        return False
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        if not netloc or "." not in netloc:
            return False
        # Reject search engine paths or internal searches
        path = parsed.path.lower()
        if path == "/search" or "search?q=" in url.lower() or "google.com" in netloc:
            return False
        # Reject local search files or search terms containing spaces or exclamation marks in host
        if " " in netloc or "!" in netloc:
            return False
        return True
    except Exception:
        return False

# Domains we must never treat as company profile links
_BLOCKED_LINK_DOMAINS = {
    "facebook.com", "twitter.com", "x.com", "instagram.com", "youtube.com",
    "play.google.com", "apps.apple.com", "chromewebstore.google.com",
    "wikipedia.org", "reddit.com", "medium.com", "github.com",
    "google.com", "apple.com", "microsoft.com",
}

# Platform-specific path patterns that confirm a URL is a company profile
_PROFILE_PATTERNS: list[tuple[str, str]] = [
    ("clutch.co",       "/profile/"),
    ("goodfirms.co",    "/company/"),
    ("linkedin.com",    "/company/"),
    ("wellfound.com",   "/company/"),
    ("crunchbase.com",  "/organization/"),
    ("zoominfo.com",    "/c/"),
    ("apollo.io",       "/companies/"),
]

# Generic path segments that suggest a company profile on unknown platforms
_GENERIC_PROFILE_SIGNALS = (
    "/company/",
    "/organization/",
    "/profile/",
    "/profiles/",
    "/business/",
    "/businesses/",
    "/c/",
)


def _is_blocked(url: str) -> bool:
    domain = urlparse(url).netloc.lower().lstrip("www.")
    return any(bd in domain for bd in _BLOCKED_LINK_DOMAINS)


def _is_company_profile_url(url: str) -> bool:
    """Return True when the URL looks like a company profile page (not a list/search/landing)."""
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    path = parsed.path.lower()

    for domain_part, profile_prefix in _PROFILE_PATTERNS:
        if domain_part in domain and path.startswith(profile_prefix):
            remainder = path[len(profile_prefix):]
            if remainder:
                return True

    if not _is_blocked(url):
        return any(sig in path for sig in _GENERIC_PROFILE_SIGNALS)

    return False


def extract_company_links(html: str, base_url: str) -> list[str]:
    """
    Parse a directory/listing HTML page and return deduplicated, absolute
    company profile URLs.

    Parameters
    ----------
    html     : Raw HTML of the directory page.
    base_url : Canonical URL of that page (used to resolve relative hrefs).

    Returns
    -------
    list[str]
        Up to MAX_LINKS_PER_DIRECTORY unique company profile URLs.
    """
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    results: list[str] = []

    for a in soup.find_all("a", href=True):
        if len(results) >= MAX_LINKS_PER_DIRECTORY:
            break

        href = a["href"].strip()
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue

        abs_url = urljoin(base_url, href)
        parsed = urlparse(abs_url)
        clean_url = parsed._replace(query="", fragment="").geturl().rstrip("/")

        if not clean_url.startswith("http") or not _is_valid_url(clean_url):
            continue
        if clean_url in seen:
            continue
        if _is_blocked(clean_url):
            continue
        if not _is_company_profile_url(clean_url):
            continue

        seen.add(clean_url)
        results.append(clean_url)

    logger.info("[DirectoryExtractor] Extracted %d company links from %s", len(results), base_url)
    return results


def extract_company_links_from_text(text: str, base_url: str) -> list[str]:
    """Fallback: regex-based extraction for lightly-structured HTML."""
    pattern = re.compile(
        r'https?://[^\s"\'<>]+(?:/company/|/profile/|/organization/|/c/)[^\s"\'<>]+'
    )
    found = pattern.findall(text)
    seen: set[str] = set()
    results: list[str] = []

    for url in found:
        clean = url.rstrip(".,;)\"'")
        if clean in seen or _is_blocked(clean):
            continue
        seen.add(clean)
        results.append(clean)
        if len(results) >= MAX_LINKS_PER_DIRECTORY:
            break

    return results
