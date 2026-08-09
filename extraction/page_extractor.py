

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

# Maps domain substring → clean key used in the output dict
SOCIAL_DOMAIN_MAP = {
    "linkedin.com":   "linkedin",
    "twitter.com":    "twitter",
    "x.com":          "twitter",   # X is twitter's successor
    "facebook.com":   "facebook",
    "instagram.com":  "instagram",
    "github.com":     "github",
    "youtube.com":    "youtube",
    "youtu.be":       "youtube",
    "linktree.ee":    "linktree",
    "linktr.ee":      "linktree",
}
# Keep backward-compat list for any code that iterates SOCIAL_DOMAINS
SOCIAL_DOMAINS = list(SOCIAL_DOMAIN_MAP.keys())

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
    "services_page": [
        "services",
        "our-services",
        "what-we-do",
        "solutions",
        "offerings",
    ],
    "products_page": [
        "products",
        "our-products",
        "product",
        "platform",
    ],
    "privacy_page": [
        "privacy",
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

    from utils.deadline import Deadline
    if Deadline.is_exceeded():
        print(f"[page_extractor] Global deadline exceeded for {canonical_url}. Skipping.")
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
        if resp.status_code == 404:
            print(f"[page_extractor] 404 Not Found for {canonical_url}. Direct fail, no retry.")
            return None
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
            if Deadline.is_exceeded():
                print(f"[page_extractor] Global deadline exceeded for {canonical_url} before attempt {attempt}. Aborting.")
                break

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
                if resp.status_code == 404:
                    print(f"[page_extractor] 404 Not Found for {canonical_url} via proxy. Fail fast, no retry.")
                    return None
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
    """Extract all email addresses visible in raw HTML, including mailto: links."""
    if not html:
        return []
    emails = []
    
    # 1. Regex findall on raw HTML
    emails.extend(EMAIL_PATTERN.findall(html))
    
    # 2. Parse mailto: links from href attributes
    try:
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if href.lower().startswith("mailto:"):
                # Remove mailto: prefix and any query parameters (e.g. ?subject=...)
                email_part = href[7:].split("?")[0].strip()
                # URL decode in case it is URL encoded
                from urllib.parse import unquote
                email_part = unquote(email_part)
                if EMAIL_PATTERN.match(email_part):
                    emails.append(email_part)
    except Exception as exc:
        print(f"[page_extractor] Error parsing mailto links: {exc}")
        
    return list(set(emails))


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
    """Extract social media profile links from the page.

    Returns a dict keyed by clean platform name (e.g. "github", "youtube")
    rather than by raw domain.  x.com and twitter.com both map to "twitter".
    """
    if not html:
        return {}
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception as exc:  # noqa: BLE001
        print(f"[page_extractor] HTML parse error in social extraction: {exc}")
        return {}
    links: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        try:
            href = urljoin(base_url, a["href"])
            domain = urlparse(href).netloc.lower()
            for social_domain, platform_key in SOCIAL_DOMAIN_MAP.items():
                if social_domain in domain and platform_key not in links:
                    links[platform_key] = href
                    break
        except Exception:  # noqa: BLE001
            continue
    return links


def extract_structured_contact_info(html: str) -> dict:
    """
    Parse JSON-LD and microdata (schema.org) from HTML.
    Returns a dict with extracted {"emails": [...], "phones": [...]}
    """
    extracted = {"emails": [], "phones": []}
    if not html:
        return extracted
    
    import json
    try:
        soup = BeautifulSoup(html, "html.parser")
        
        # 1. Parse JSON-LD blocks
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                content = script.string
                if not content:
                    continue
                content = content.strip()
                if content.startswith("/*<![CDATA[*/"):
                    content = content.replace("/*<![CDATA[*/", "").replace("/*]]>*/", "")
                
                data = json.loads(content)
                
                # Traverse JSON to find "email" or "telephone" keys recursively
                def traverse(node):
                    if isinstance(node, dict):
                        for k, v in node.items():
                            if k.lower() == "email" and isinstance(v, str):
                                clean_email = v.replace("mailto:", "").strip()
                                if "@" in clean_email:
                                    extracted["emails"].append(clean_email)
                            elif k.lower() == "telephone" and isinstance(v, str):
                                extracted["phones"].append(v.strip())
                            else:
                                traverse(v)
                    elif isinstance(node, list):
                        for item in node:
                            traverse(item)
                
                traverse(data)
            except Exception:
                continue
                
        # 2. Parse standard schema.org microdata (itemprop="email", itemprop="telephone")
        for elem in soup.find_all(itemprop=True):
            prop = elem["itemprop"].lower()
            if prop == "email":
                text = elem.get_text().strip() or elem.get("content", "").strip()
                text = text.replace("mailto:", "").strip()
                if "@" in text:
                    extracted["emails"].append(text)
            elif prop == "telephone":
                text = elem.get_text().strip() or elem.get("content", "").strip()
                if text:
                    extracted["phones"].append(text)
                    
    except Exception as exc:
        print(f"[page_extractor] Error parsing structured contact info: {exc}")
        
    extracted["emails"] = list(set(extracted["emails"]))
    extracted["phones"] = list(set(extracted["phones"]))
    return extracted


def find_footer_links(html: str, base_url: str) -> list:
    """
    Find links inside footer elements that might be contact or about pages.
    """
    if not html:
        return []
    links = []
    try:
        soup = BeautifulSoup(html, "html.parser")
        footers = soup.find_all(["footer", "div", "section"])
        footer_elements = []
        for elem in footers:
            if elem.name == "footer":
                footer_elements.append(elem)
            else:
                classes = [c.lower() for c in elem.get("class", []) if isinstance(c, str)]
                elem_id = (elem.get("id") or "").lower()
                if "footer" in classes or "footer" in elem_id:
                    footer_elements.append(elem)
                    
        base_netloc = urlparse(base_url).netloc.lower()
        for footer in footer_elements:
            for a in footer.find_all("a", href=True):
                try:
                    href = a["href"].strip()
                    abs_url = urljoin(base_url, a["href"])
                    if urlparse(abs_url).netloc.lower() != base_netloc:
                        continue
                    text = (a.get_text() or "").lower()
                    href_lower = href.lower()
                    
                    is_contact_link = any(kw in text or kw in href_lower for kw in [
                        "contact", "about", "team", "support", "help", "info", "reach"
                    ])
                    if is_contact_link and abs_url not in links:
                        links.append(abs_url)
                except Exception:
                    continue
    except Exception as exc:
        print(f"[page_extractor] Error extracting footer links: {exc}")
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
# Sitemap mining  (robots.txt → sitemap XML → important sub-pages)
# ─────────────────────────────────────────────────────────────────────────────

_SITEMAP_PAGE_PATTERNS = {
    "contact_page":  ["contact", "contact-us", "get-in-touch", "reach-us"],
    "about_page":    ["about", "about-us", "who-we-are", "company"],
    "team_page":     ["team", "people", "leadership", "founders", "executives"],
    "services_page": ["services", "solutions", "what-we-do", "offerings"],
    "products_page": ["products", "product", "platform"],
}


def fetch_sitemap(base_url: str) -> dict:
    """
    Read robots.txt to discover sitemap URLs, then scan each sitemap for
    Contact / About / Team / Services / Products pages.

    Returns a dict like {"contact_page": "https://...", "about_page": "https://..."}
    Only fills keys that were not already found via link discovery.
    """
    from urllib.parse import urlparse, urljoin
    try:
        from network_client_project.network import NetworkClient
        client = NetworkClient()
    except Exception:
        return {}

    found: dict[str, str] = {}
    base = base_url.rstrip("/")
    parsed = urlparse(base)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    # 1. Fetch robots.txt
    robots_url = f"{origin}/robots.txt"
    sitemap_urls: list[str] = []
    try:
        resp = client.get(robots_url, require_proxy=False, timeout=5)
        if resp and resp.status_code == 200:
            for line in (resp.text or "").splitlines():
                if line.strip().lower().startswith("sitemap:"):
                    sm_url = line.split(":", 1)[1].strip()
                    if sm_url:
                        sitemap_urls.append(sm_url)
    except Exception:
        pass

    # Always try /sitemap.xml and /sitemap_index.xml as fallback
    for fallback in ("/sitemap.xml", "/sitemap_index.xml"):
        candidate = origin + fallback
        if candidate not in sitemap_urls:
            sitemap_urls.append(candidate)

    # 2. Parse each sitemap XML (process max 3 sitemaps)
    import re as _re
    loc_pattern = _re.compile(r"<loc>(.*?)</loc>", _re.IGNORECASE | _re.DOTALL)

    for sm_url in sitemap_urls[:3]:
        if len(found) >= len(_SITEMAP_PAGE_PATTERNS):
            break
        try:
            resp = client.get(sm_url, require_proxy=False, timeout=5)
            if not resp or resp.status_code != 200:
                continue
            content = resp.text or ""
            # Handle sitemap index: extract nested sitemaps
            nested = loc_pattern.findall(content)
            for loc in nested:
                loc = loc.strip()
                if not loc:
                    continue
                # Check if this loc is a nested sitemap
                if loc.endswith(".xml") or "sitemap" in loc.lower():
                    # Recursively scan (1 level deep)
                    try:
                        sub_resp = client.get(loc, require_proxy=False, timeout=5)
                        if sub_resp and sub_resp.status_code == 200:
                            nested.extend(loc_pattern.findall(sub_resp.text or ""))
                    except Exception:
                        pass
                    continue
                # Check if this loc matches any important page pattern
                loc_lower = loc.lower()
                for page_type, patterns in _SITEMAP_PAGE_PATTERNS.items():
                    if page_type not in found:
                        if any(p in loc_lower for p in patterns):
                            found[page_type] = loc
                            break
        except Exception:
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
# Company profile field helpers
# ─────────────────────────────────────────────────────────────────────────────

_EMPLOYEES_PATTERN = re.compile(
    r"(\d[\d,]*)\s*[-–+]?\s*(\d[\d,]*)?\s*"
    r"(employees|team members|professionals|people|staff|headcount|workforce)",
    re.IGNORECASE,
)
_FOUNDED_PATTERN = re.compile(
    r"(?:founded|established|incorporated|since|est\.?)\s+(?:in\s+)?(\d{4})",
    re.IGNORECASE,
)


def _extract_employees(text: str) -> str:
    """Extract employee count/range from page text."""
    m = _EMPLOYEES_PATTERN.search(text or "")
    if not m:
        return ""
    lo = m.group(1).replace(",", "")
    hi = m.group(2)
    if hi:
        return f"{lo}-{hi.replace(',', '')}"
    return lo


def _extract_founded(html: str) -> str:
    """Extract founding year from JSON-LD or visible text."""
    # 1. Try JSON-LD first
    try:
        import json as _json
        from bs4 import BeautifulSoup as _BS
        soup = _BS(html, "html.parser")
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = _json.loads(script.string or "")
                def _seek(node):
                    if isinstance(node, dict):
                        for k, v in node.items():
                            if k.lower() in ("foundingyear", "foundingdate") and v:
                                return str(v)[:4]
                            r = _seek(v)
                            if r:
                                return r
                    elif isinstance(node, list):
                        for item in node:
                            r = _seek(item)
                            if r:
                                return r
                    return None
                found = _seek(data)
                if found and found.isdigit():
                    return found
            except Exception:
                continue
    except Exception:
        pass
    # 2. Regex on plain text
    try:
        from bs4 import BeautifulSoup as _BS
        text = _BS(html, "html.parser").get_text(" ")
        m = _FOUNDED_PATTERN.search(text)
        if m:
            return m.group(1)
    except Exception:
        pass
    return ""


def _extract_country(html: str) -> str:
    """Extract country from JSON-LD address or <address> tags."""
    try:
        import json as _json
        from bs4 import BeautifulSoup as _BS
        soup = _BS(html, "html.parser")
        # JSON-LD
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = _json.loads(script.string or "")
                def _seek_country(node):
                    if isinstance(node, dict):
                        addr = node.get("address") or {}
                        if isinstance(addr, dict):
                            country = addr.get("addressCountry") or addr.get("country")
                            if country:
                                return str(country)
                        for v in node.values():
                            r = _seek_country(v)
                            if r:
                                return r
                    elif isinstance(node, list):
                        for item in node:
                            r = _seek_country(item)
                            if r:
                                return r
                    return None
                found = _seek_country(data)
                if found:
                    return found
            except Exception:
                continue
        # itemprop="addressCountry"
        for elem in soup.find_all(itemprop="addressCountry"):
            v = (elem.get("content") or elem.get_text()).strip()
            if v:
                return v
    except Exception:
        pass
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Main extraction entry-point  (Tasks 5, 6, 7 + new profile fields)
# ─────────────────────────────────────────────────────────────────────────────

def extract_from_website(homepage_url: str, homepage_html: str | None = None) -> dict:
    """
    Full public-data extraction pass:
    homepage → contact/about/team/services/products subpages
             → emails, phones, socials, people.

    New fields added in this revision
    ----------------------------------
    tech_stack        : detected frontend/backend technologies (list)
    services_page     : URL of the services page if discovered
    products_page     : URL of the products page if discovered
    employees         : employee count/range string if found on site
    founded           : founding year string if found
    country           : country from structured data / address tags
    description       : rich description (meta + about text, 800 chars)
    emails_scored     : list of {email, confidence} dicts (after scoring)

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
        "services_page":     None,
        "products_page":     None,
        "emails":            [],
        "emails_scored":     [],
        "phones":            [],
        "social_links":      {},
        "people":            [],
        "company_type":      "Unknown",
        "industry_detected": "Unknown",
        "meta_description":  "",
        "tech_stack":        [],
        "employees":         "",
        "founded":           "",
        "country":           "",
        "description":       "",
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

    # Extract structured contact info from homepage
    struct_info = extract_structured_contact_info(homepage_html)
    result["emails"].extend(struct_info["emails"])
    result["phones"].extend(struct_info["phones"])

    # ── Tech stack detection ──────────────────────────────────────────────
    try:
        from extraction.tech_detector import detect_tech_stack
        result["tech_stack"] = detect_tech_stack(homepage_html, {})
    except Exception:
        pass

    # ── Tasks 6 & 7: Enrichment from meta / headings ──────────────────────
    meta_text = extract_meta_text(homepage_html)
    result["meta_description"] = meta_text[:500] if meta_text else ""
    result["company_type"] = detect_company_type(meta_text)
    result["industry_detected"] = detect_industry(meta_text)

    # ── Profile field extraction from homepage ────────────────────────────
    try:
        from bs4 import BeautifulSoup as _BS
        hp_text = _BS(homepage_html, "html.parser").get_text(" ")
    except Exception:
        hp_text = ""
    result["employees"] = _extract_employees(hp_text)
    result["founded"]   = _extract_founded(homepage_html)
    result["country"]   = _extract_country(homepage_html)
    result["description"] = meta_text[:800] if meta_text else ""

    # ── Discover sub-pages via link scanning ─────────────────────────────
    subpages = find_subpages(homepage_html, homepage_url)
    result["contact_page"]  = subpages.get("contact_page")
    result["about_page"]    = subpages.get("about_page")
    result["team_page"]     = subpages.get("team_page")
    result["services_page"] = subpages.get("services_page")
    result["products_page"] = subpages.get("products_page")

    # ── Sitemap fallback for pages not found via links ────────────────────
    missing_pages = [k for k in ("contact_page", "about_page", "team_page",
                                  "services_page", "products_page")
                     if not result[k]]
    if missing_pages:
        sitemap_pages = fetch_sitemap(homepage_url)
        for page_type in missing_pages:
            if page_type in sitemap_pages:
                result[page_type] = sitemap_pages[page_type]

    # ── Hard fallback paths for critical pages ────────────────────────────
    if not result["contact_page"]:
        result["contact_page"] = urljoin(homepage_url, "/contact")
    if not result["about_page"]:
        result["about_page"] = urljoin(homepage_url, "/about")

    # ── Consolidate pages to crawl ────────────────────────────────────────
    pages_to_scrape: dict[str, str] = {}
    for page_type in ("contact_page", "about_page", "team_page",
                      "services_page", "products_page"):
        url = result[page_type]
        if url:
            pages_to_scrape[url] = page_type

    # Follow footer contact/about links (limit to 2 extra)
    footer_links = find_footer_links(homepage_html, homepage_url)
    extra_crawled = 0
    for link in footer_links:
        if link not in pages_to_scrape and extra_crawled < 2:
            pages_to_scrape[link] = "footer_link"
            extra_crawled += 1

    # ── Sub-page passes ───────────────────────────────────────────────────
    for url, page_type in pages_to_scrape.items():
        html = fetch_page(url)
        if not html:
            continue

        # 1. Standard text-based extraction
        result["emails"].extend(extract_emails(html))
        result["phones"].extend(extract_phone_numbers(html))

        # 2. Structured JSON-LD / microdata extraction
        sub_struct = extract_structured_contact_info(html)
        result["emails"].extend(sub_struct["emails"])
        result["phones"].extend(sub_struct["phones"])

        # Improve enrichment if about/services page has more content
        if page_type in ("about_page", "services_page", "products_page"):
            page_meta = extract_meta_text(html)
            if result["industry_detected"] == "Unknown":
                result["industry_detected"] = detect_industry(page_meta)
            if result["company_type"] == "Unknown":
                result["company_type"] = detect_company_type(page_meta)
            # Richer description from about page
            if page_type == "about_page" and not result["description"]:
                result["description"] = page_meta[:800]
            # Profile fields from about page (override blanks)
            if not result["employees"]:
                try:
                    from bs4 import BeautifulSoup as _BS
                    pg_text = _BS(html, "html.parser").get_text(" ")
                    result["employees"] = _extract_employees(pg_text)
                except Exception:
                    pass
            if not result["founded"]:
                result["founded"] = _extract_founded(html)
            if not result["country"]:
                result["country"] = _extract_country(html)

        if page_type == "team_page":
            result["people"].extend(extract_people(html))

    # ── Final dedup + ranking ─────────────────────────────────────────────
    result["emails"] = rank_emails(result["emails"])
    result["phones"] = sorted(set(result["phones"]))

    # ── Email confidence scoring ──────────────────────────────────────────
    try:
        from utils.validators import score_email
        company_domain = urlparse(homepage_url).netloc.lower().lstrip("www.")
        result["emails_scored"] = [
            score_email(email, company_domain)
            for email in result["emails"]
        ]
    except Exception:
        pass

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Manual test entry-point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    print(json.dumps(extract_from_website("https://anthropic.com"), indent=2))

