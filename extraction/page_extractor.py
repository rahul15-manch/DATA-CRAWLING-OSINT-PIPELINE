

import re
from urllib.parse import urljoin, urlparse
import threading
import time

import requests
from bs4 import BeautifulSoup

import config
from utils.constants import DESIGNATION_KEYWORDS, DESIGNATION_ACRONYMS
from utils.validators import is_valid_phone, is_valid_person_record, rank_emails
from utils.enrichment import detect_company_type, detect_industry

# Domain Crawl Circuit Breaker state
_domain_consecutive_blocks = {}
_domain_cooldowns = {}
_cb_lock = threading.Lock()

# ── Patterns ──────────────────────────────────────────────────────────────────

EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_CAPTURE_PATTERN = re.compile(r"(\+?[\d(][\d\s\-().]{5,20}[\d])")

SOCIAL_DOMAINS = [
    "linkedin.com",
    "twitter.com",
    "x.com",
    "facebook.com",
    "instagram.com",
]

# ── Sub-page keyword map (Task 5 — expanded) ──────────────────────────────────

PAGE_KEYWORDS = {
    "contact_page": [
        "contact",
        "contact-us",
        "get-in-touch",
        "reach-us",
    ],
    "about_page": [
        "about",
        "about-us",
        "company",
        "who-we-are",
    ],
    "team_page": [
        "team",
        "our-team",
        "people",
        "leadership",
        "management",
        "founders",
        "executives",
        "board",
        "directors",
    ],
    "careers_page": [
        "careers",
        "jobs",
        "join-us",
        "work-with-us",
    ],
    "privacy_page": [
        "privacy",
        "privacy-policy",
        "privacy-policy",
        "data-protection",
    ],
}

_HTML_CONTENT_TYPES = ("text/html", "application/xhtml")


# Thread-local crawl budget tracking
import threading
import time

_crawl_budgets = threading.local()

def _get_domain_budget_state(domain: str):
    if not hasattr(_crawl_budgets, "domains"):
        _crawl_budgets.domains = {}
    if domain not in _crawl_budgets.domains:
        _crawl_budgets.domains[domain] = {
            "pages_crawled": 0,
            "bytes_downloaded": 0,
            "start_time": time.time()
        }
    return _crawl_budgets.domains[domain]


# ─────────────────────────────────────────────────────────────────────────────
# Fetch helper
# ─────────────────────────────────────────────────────────────────────────────

def _penalise_proxy(proxy_url: str, canonical_url: str):
    try:
        from network_client_project.network.proxy_manager import get_proxy_manager
        from urllib.parse import urlparse as _up
        pm = get_proxy_manager()
        proxy_obj = pm.get_proxy_by_url(proxy_url)
        if proxy_obj:
            proxy_obj.record_failure(domain=_up(canonical_url).netloc, reason="CHALLENGE_PAGE")
            print(f"[page_extractor] Penalised proxy {proxy_url} for delivering non-HTML content.")
    except Exception:
        pass


def fetch_page(url: str):
    """
    Fetch a page's public HTML via a plain GET using NetworkClient.
    Applies RobotsChecker compliance, canonicalization, crawl budget, and duplicate content hashing.
    """
    from network_client_project.network import NetworkClient
    from network_client_project.network.robots import RobotsChecker
    from network_client_project.network.frontier import get_frontier

    frontier = get_frontier()
    robots_checker = RobotsChecker()

    canonical_url = frontier.canonicalize_url(url)
    if not canonical_url:
        return None

    if not robots_checker.allowed(canonical_url):
        print(f"[Robots] Crawl of {canonical_url} disallowed by robots.txt")
        return None

    from urllib.parse import urlparse
    domain = urlparse(canonical_url).netloc.lower()
    domain_key = domain.lstrip("www.")

    # Check domain-level circuit breaker cooldown
    with _cb_lock:
        cooldown_until = _domain_cooldowns.get(domain_key, 0.0)
        if time.time() < cooldown_until:
            remaining = int(cooldown_until - time.time())
            print(f"[CrawlCircuitBreaker] Skipping {canonical_url} — domain {domain_key} is in cooldown for {remaining}s due to consecutive blocks.")
            return None

    state = _get_domain_budget_state(domain)

    if state["pages_crawled"] >= 4:
        print(f"[CrawlBudget] Aborted {canonical_url} - hit max 4 pages limit.")
        return None
    if state["bytes_downloaded"] >= 2 * 1024 * 1024:
        print(f"[CrawlBudget] Aborted {canonical_url} - hit max 2 MB download limit.")
        return None
    if time.time() - state["start_time"] >= 20.0:
        print(f"[CrawlBudget] Aborted {canonical_url} - hit max 20s time budget limit.")
        return None

    if not frontier.should_crawl(canonical_url):
        return None

    client = NetworkClient()
    resp = None
    success = False

    try:
        # Try direct connection first
        resp = client.get(canonical_url, require_proxy=False, timeout=config.REQUEST_TIMEOUT)
        if resp.status_code in (403, 429) or str(resp.status_code).startswith("5"):
            raise Exception(f"Direct connection failed with HTTP {resp.status_code}")

        # Check if direct request returned valid HTML
        content_type = (resp.headers.get("Content-Type") or resp.headers.get("content-type") or "").lower()
        if resp.status_code == 200 and any(ct in content_type for ct in _HTML_CONTENT_TYPES):
            success = True
    except Exception as exc:
        print(f"[page_extractor] Direct fetch failed for {canonical_url} ({exc}), retrying with proxy...")

    if not success:
        # Try up to 3 different unique proxies
        exclude_urls = set()
        for attempt in range(1, 4):
            session_id = f"enrichment_{domain_key}_{attempt}"
            try:
                # Get a unique proxy (exclude_urls prevents re-using previously tried proxies)
                resp = client.get(
                    canonical_url,
                    require_proxy=True,
                    session_id=session_id,
                    timeout=config.REQUEST_TIMEOUT,
                    exclude_urls=exclude_urls
                )
                proxy_used = getattr(resp, "proxy", None)
                if proxy_used:
                    exclude_urls.add(proxy_used)

                if resp.status_code == 200:
                    content_type = (resp.headers.get("Content-Type") or resp.headers.get("content-type") or "").lower()
                    if any(ct in content_type for ct in _HTML_CONTENT_TYPES):
                        success = True
                        break
                    else:
                        print(f"[page_extractor] Proxy attempt {attempt} returned non-HTML response from {canonical_url}")
                        if proxy_used and proxy_used != "direct":
                            _penalise_proxy(proxy_used, canonical_url)
                else:
                    print(f"[page_extractor] Proxy attempt {attempt} returned HTTP {resp.status_code} for {canonical_url}")
            except Exception as proxy_exc:
                print(f"[page_extractor] Proxy attempt {attempt} failed for {canonical_url}: {proxy_exc}")
                resp = None

    # Handle success/failure transitions for Domain-level Circuit Breaker
    if not success:
        with _cb_lock:
            blocks = _domain_consecutive_blocks.get(domain_key, 0) + 1
            _domain_consecutive_blocks[domain_key] = blocks
            if blocks >= 10:
                _domain_cooldowns[domain_key] = time.time() + 1200.0  # 20 minutes cooldown
                print(f"[CrawlCircuitBreaker] Domain {domain_key} hit 10 consecutive blocks. Circuit opened for 20 minutes.")
        return None

    # Reset block count on success
    with _cb_lock:
        _domain_consecutive_blocks[domain_key] = 0

    try:
        # Track bytes and page counts
        state["pages_crawled"] += 1
        downloaded_bytes = len(resp.content or b"")
        state["bytes_downloaded"] += downloaded_bytes

        html = resp.text

        if not frontier.record_crawl(canonical_url, html):
            return None

        return html

    except Exception as exc:  # noqa: BLE001
        print(f"[page_extractor] failed to process {canonical_url}: {exc}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Meta extraction helpers (Tasks 6 & 7)
# ─────────────────────────────────────────────────────────────────────────────

def extract_meta_text(html: str) -> str:
    """
    Extract the most informative plain text from a page for enrichment.

    Combines: <title>, <meta name="description">, first 5 <h1>/<h2> tags.
    Returns a single plain-text string (no HTML).
    """
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "html.parser")
        parts = []

        # Title
        if soup.title:
            parts.append(soup.title.get_text(" ", strip=True))

        # Meta description
        for meta in soup.find_all("meta"):
            name = (meta.get("name") or meta.get("property") or "").lower()
            if "description" in name or "og:description" in name:
                content = meta.get("content") or ""
                if content:
                    parts.append(content)

        # First few headings
        for tag in soup.find_all(["h1", "h2"], limit=5):
            text = tag.get_text(" ", strip=True)
            if text:
                parts.append(text)

        return " ".join(parts)

    except Exception as exc:  # noqa: BLE001
        print(f"[page_extractor] meta extraction error: {exc}")
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# Extraction helpers
# ─────────────────────────────────────────────────────────────────────────────

def extract_emails(html: str) -> list:
    """Extract all email addresses visible in raw HTML."""
    if not html:
        return []
    return list(set(EMAIL_PATTERN.findall(html)))


def extract_phone_numbers(html: str) -> list:
    """
    Extract and validate phone numbers from page text.

    Each candidate is passed through is_valid_phone(), which rejects
    dates (01.04.2026), year ranges (2025-2026), multi-line table values,
    and time strings (10.30-12.00).
    """
    if not html:
        return []
    try:
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ")
    except Exception as exc:  # noqa: BLE001
        print(f"[page_extractor] HTML parse error in phone extraction: {exc}")
        return []

    candidates = PHONE_CAPTURE_PATTERN.findall(text)
    validated = []
    for raw in candidates:
        cleaned = raw.strip()
        if is_valid_phone(cleaned) and cleaned not in validated:
            validated.append(cleaned)
    return validated


def extract_social_links(html: str, base_url: str) -> dict:
    """Extract social media profile links from the page."""
    if not html:
        return {}
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception as exc:  # noqa: BLE001
        print(f"[page_extractor] HTML parse error in social extraction: {exc}")
        return {}
    links = {}
    for a in soup.find_all("a", href=True):
        try:
            href = urljoin(base_url, a["href"])
            domain = urlparse(href).netloc.lower()
            for social in SOCIAL_DOMAINS:
                if social in domain and social not in links:
                    links[social] = href
        except Exception:  # noqa: BLE001
            continue
    return links


def find_subpages(html: str, base_url: str) -> dict:
    """
    Scan the homepage's own links for contact / about / team sub-pages.

    Extended keyword set covers leadership, management, founders, executives.
    """
    if not html:
        return {}
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception as exc:  # noqa: BLE001
        print(f"[page_extractor] HTML parse error in subpage discovery: {exc}")
        return {}

    found = {}
    base_netloc = urlparse(base_url).netloc.lower()

    for a in soup.find_all("a", href=True):
        try:
            raw_href = a["href"]
            text = (a.get_text() or "").lower().strip()
            href_lower = raw_href.lower()
            abs_url = urljoin(base_url, raw_href)

            if urlparse(abs_url).netloc.lower() != base_netloc:
                continue
            if abs_url.rstrip("/") == base_url.rstrip("/"):
                continue

            for page_type, keywords in PAGE_KEYWORDS.items():
                if page_type in found:
                    continue
                if any(kw in text or kw in href_lower for kw in keywords):
                    found[page_type] = abs_url
        except Exception:  # noqa: BLE001
            continue

    return found


# ─────────────────────────────────────────────────────────────────────────────
# People extraction (Task 8)
# ─────────────────────────────────────────────────────────────────────────────

def _format_designation(kw: str) -> str:
    """Format a designation keyword for output."""
    kw = kw.strip()
    if kw.lower() in DESIGNATION_ACRONYMS:
        return kw.upper()
    return kw.title()


def extract_people(html: str) -> list:
    """
    Best-effort extraction of (name, designation) pairs from a team / about page.

    Every extracted record is validated with is_valid_person_record().
    Bare designations without a realistic human name are silently dropped.
    """
    if not html:
        return []

    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception as exc:  # noqa: BLE001
        print(f"[page_extractor] HTML parse error in people extraction: {exc}")
        return []

    people = []
    blocks = soup.find_all(["h1", "h2", "h3", "h4", "p", "span", "div"])

    for i, block in enumerate(blocks):
        try:
            text = block.get_text(" ", strip=True)
            if not text or len(text) > 120:
                continue

            lowered = text.lower()
            for kw in DESIGNATION_KEYWORDS:
                if kw in lowered:
                    name_candidate = None
                    if i > 0:
                        prev_text = blocks[i - 1].get_text(" ", strip=True)
                        if prev_text and 1 <= len(prev_text.split()) <= 5:
                            name_candidate = prev_text

                    record = {
                        "name": name_candidate,
                        "designation": _format_designation(kw),
                    }

                    if is_valid_person_record(record):
                        people.append(record)
                    break

        except Exception:  # noqa: BLE001
            continue

    return people


# ─────────────────────────────────────────────────────────────────────────────
# Main extraction entry-point  (Tasks 5, 6, 7)
# ─────────────────────────────────────────────────────────────────────────────

def extract_from_website(homepage_url: str, homepage_html: str | None = None) -> dict:
    """
    Full public-data extraction pass:
    homepage → contact/about/team subpages → emails, phones, socials, people.

    New fields added in this revision
    ----------------------------------
    company_type      (Task 6): Software Company / Consultancy / Agency / …
    industry_detected (Task 7): Artificial Intelligence / Cloud Computing / …
    meta_description  : raw meta description text for downstream use

    Task 5: All fetch failures are caught; pipeline never crashes for one URL.
    Task 6: Emails are ranked and deduplicated via rank_emails().
    Task 7: Phones are validated; dates / year-ranges are excluded.
    Task 8: People are filtered through is_valid_person_record().
    """
    result = {
        "contact_page":      None,
        "about_page":        None,
        "team_page":         None,
        "emails":            [],
        "phones":            [],
        "social_links":      {},
        "people":            [],
        "company_type":      "Unknown",
        "industry_detected": "Unknown",
        "meta_description":  "",
    }

    from urllib.parse import urlparse
    domain = urlparse(homepage_url).netloc.lower()
    state = _get_domain_budget_state(domain)
    state["pages_crawled"] = 0
    state["bytes_downloaded"] = 0
    state["start_time"] = time.time()

    if not homepage_html:
        homepage_html = fetch_page(homepage_url)
    else:
        # Pre-fetched homepage: record it as 1 page and estimate size
        state["pages_crawled"] = 1
        state["bytes_downloaded"] = len(homepage_html.encode("utf-8") if isinstance(homepage_html, str) else homepage_html)

    if not homepage_html:
        return result

    # ── Homepage pass ─────────────────────────────────────────────────────
    result["social_links"] = extract_social_links(homepage_html, homepage_url)
    result["emails"].extend(extract_emails(homepage_html))
    result["phones"].extend(extract_phone_numbers(homepage_html))

    # ── Tasks 6 & 7: Enrichment from meta / headings ──────────────────────
    meta_text = extract_meta_text(homepage_html)
    result["meta_description"] = meta_text[:500] if meta_text else ""
    result["company_type"] = detect_company_type(meta_text)
    result["industry_detected"] = detect_industry(meta_text)

    # ── Discover sub-pages ────────────────────────────────────────────────
    subpages = find_subpages(homepage_html, homepage_url)
    result["contact_page"] = subpages.get("contact_page")
    result["about_page"] = subpages.get("about_page")
    result["team_page"] = subpages.get("team_page")

    # ── Sub-page passes ───────────────────────────────────────────────────
    for page_type in ("contact_page", "about_page", "team_page"):
        url = result[page_type]
        if not url:
            continue
        html = fetch_page(url)
        if not html:
            continue
        result["emails"].extend(extract_emails(html))
        result["phones"].extend(extract_phone_numbers(html))
        # Improve enrichment if about page has more content
        if page_type == "about_page" and result["industry_detected"] == "Unknown":
            about_meta = extract_meta_text(html)
            result["industry_detected"] = detect_industry(about_meta)
            if result["company_type"] == "Unknown":
                result["company_type"] = detect_company_type(about_meta)
        if page_type == "team_page":
            result["people"].extend(extract_people(html))

    # ── Final dedup + ranking ─────────────────────────────────────────────
    result["emails"] = rank_emails(result["emails"])
    result["phones"] = sorted(set(result["phones"]))

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Manual test entry-point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    print(json.dumps(extract_from_website("https://anthropic.com"), indent=2))
