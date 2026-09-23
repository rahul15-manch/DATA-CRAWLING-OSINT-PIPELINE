

import re
from urllib.parse import urljoin, urlparse
import threading
import time

import requests
from bs4 import BeautifulSoup

import config
from utils.constants import DESIGNATION_KEYWORDS, DESIGNATION_ACRONYMS
from utils.validators import is_valid_phone, is_valid_person_record, rank_emails, is_valid_email_candidate
from utils.enrichment import detect_company_type, detect_industry
from utils.provenance import (
    make_fact,
    SRC_HOMEPAGE_MAILTO,
    SRC_HOMEPAGE_TEXT,
    SRC_HOMEPAGE_STRUCTURED,
    SRC_CONTACT_PAGE_TEXT,
    SRC_CONTACT_PAGE_STRUCTURED,
    SRC_ABOUT_PAGE_TEXT,
    SRC_ABOUT_PAGE_STRUCTURED,
    SRC_TEAM_PAGE_TEXT,
    SRC_SEARCH_RESULT_SNIPPET,
    SRC_JSON_LD_HOMEPAGE,
    SRC_JSON_LD_SUBPAGE,
    SRC_META_GEO_TAG,
)

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

_DISALLOWED_SUBPAGE_SEGMENTS = frozenset({
    "checkout", "cart", "basket", "login", "signin", "signup", "register",
    "account", "payment", "payments", "pay", "order", "orders", "track", "tracking",
    "refund", "refunds", "disclaimer", "cookie", "cookies", "legal", "faq", "faqs",
    "terms", "terms-of-service", "terms-and-conditions",
    "auth", "oauth", "password", "reset-password", "forgot-password",
    "download", "app", "ios", "android", "cart.php", "checkout.php",
    "login.php", "cart.html", "checkout.html"
})

_HIGH_VALUE_SUBPAGE_KEYWORDS = frozenset({
    "about", "contact", "team", "leadership", "company", "people", "careers",
    "services", "products", "management", "executives", "founders"
})


def is_disallowed_subpage_url(url: str, text: str = "") -> bool:
    """
    Return True if url or link text targets transactional, auth, cart, or noise pages.
    """
    if not url:
        return True
    try:
        from urllib.parse import urlparse
        import re
        parsed = urlparse(url)
        path = parsed.path.lower()
        query = parsed.query.lower()
        text_lower = (text or "").lower().strip()

        # Reject disallowed file extensions
        if any(path.endswith(ext) for ext in (
            ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".css", ".js",
            ".zip", ".tar", ".gz", ".apk", ".ipa", ".exe"
        )):
            return True

        # Split path & query into tokens
        tokens = set(re.findall(r"[a-z0-9]+", f"{path} {query}"))
        if any(seg in _DISALLOWED_SUBPAGE_SEGMENTS or seg.rstrip("s") in _DISALLOWED_SUBPAGE_SEGMENTS for seg in tokens):
            return True

        # Check strong transactional text phrases
        if text_lower:
            disallowed_text_phrases = (
                "order now", "cart", "checkout", "log in", "sign in", "sign up",
                "track order", "my account", "place order", "terms of use",
                "terms & conditions", "cookie policy"
            )
            if any(phrase in text_lower for phrase in disallowed_text_phrases):
                return True
    except Exception:
        return True
    return False

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


def has_useful_company_content(html: str) -> bool:
    """
    Check if the fetched HTML has rich company signals or if it's a minimal JS shell / captcha block.
    """
    if not html:
        return False
    
    # Very small HTML payloads are almost certainly JS shells or redirects
    if len(html) < 5000:
        return False

    # Check for strong structured data
    if "application/ld+json" in html.lower():
        return True
    
    # Check for meta description
    html_lower = html.lower()
    if "<meta" in html_lower and ("name=\"description\"" in html_lower or "property=\"og:description\"" in html_lower):
        return True

    # Check body text length
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        body_text = soup.get_text(" ", strip=True)
        if len(body_text) > 300:
            return True
    except Exception:
        pass

    return False


from utils.deadline import Deadline, DeadlineExceeded


def _playwright_fetch(url: str, deadline: Deadline | None = None) -> str | None:
    """
    Fallback browser fetch using Playwright to execute JavaScript and render client-side pages.
    """
    if deadline:
        if deadline.is_exceeded() or deadline.bounded_timeout(15.0) < 1.0:
            raise DeadlineExceeded(f"Deadline exceeded before Playwright fetch for {url}")
        pw_timeout = int(deadline.bounded_timeout(15.0) * 1000) if deadline else 15000

    from utils.validators import is_safe_url
    is_safe, reason = is_safe_url(url)
    if not is_safe:
        print(f"[page_extractor] SSRF defense rejected Playwright navigation to {url}: {reason}")
        return None

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800}
            )
            page = context.new_page()
            page.goto(url, timeout=pw_timeout, wait_until="domcontentloaded")
            page.wait_for_timeout(1000)
            rendered_html = page.content()
            browser.close()
            if rendered_html and len(rendered_html) > 5000:
                print(f"[page_extractor] Playwright successfully rendered {url} ({len(rendered_html)} bytes)")
                return rendered_html
    except DeadlineExceeded:
        raise
    except Exception as exc:
        print(f"[page_extractor] Playwright fallback failed for {url}: {exc}")
    return None


def fetch_page(url: str, deadline: Deadline | None = None):
    """
    Fetch a page's public HTML via a plain GET using NetworkClient.
    Applies RobotsChecker compliance, canonicalization, crawl budget, and duplicate content hashing.
    If plain HTTP returns a minimal JS shell, falls back to Playwright rendering.
    """
    from utils.validators import is_safe_url
    is_safe, reason = is_safe_url(url)
    if not is_safe:
        print(f"[page_extractor] SSRF defense rejected crawl to {url}: {reason}")
        return None

    from network_client_project.network import NetworkClient
    from network_client_project.network.robots import RobotsChecker
    from network_client_project.network.frontier import get_frontier

    if deadline:
        if deadline.is_exceeded() or deadline.bounded_timeout(config.REQUEST_TIMEOUT) == 0.0:
            raise DeadlineExceeded(f"Deadline exceeded before fetching {url}")
        req_timeout = deadline.bounded_timeout(config.REQUEST_TIMEOUT)
    else:
        req_timeout = config.REQUEST_TIMEOUT

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
    # Time-budget check: prefer deadline-aware check over independent wall clock.
    if deadline:
        try:
            deadline.require(1.0)
        except Exception:
            print(f"[CrawlBudget] Aborted {canonical_url} - deadline exhausted (< 1s remaining).")
            return None
    elif time.time() - state["start_time"] >= 20.0:
        print(f"[CrawlBudget] Aborted {canonical_url} - hit max 20s time budget limit.")
        return None

    if not frontier.should_crawl(canonical_url):
        return None

    client = NetworkClient()
    resp = None
    success = False

    try:
        # Try direct connection first
        resp = client.get(canonical_url, require_proxy=False, timeout=req_timeout, deadline=deadline)
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
            if deadline and deadline.is_exceeded():
                raise DeadlineExceeded(f"Deadline exceeded for {canonical_url} before proxy attempt {attempt}")

            session_id = f"enrichment_{domain_key}_{attempt}"
            try:
                # Get a unique proxy (exclude_urls prevents re-using previously tried proxies)
                resp = client.get(
                    canonical_url,
                    require_proxy=True,
                    session_id=session_id,
                    timeout=req_timeout,
                    exclude_urls=exclude_urls,
                    deadline=deadline,
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

        # Evaluate if plain HTTP returned sufficient content, or if we need Playwright rendering
        if not (len(html) >= 15000 or has_useful_company_content(html)):
            print(f"[page_extractor] Insufficient HTML ({len(html)} bytes) for {canonical_url}. Falling back to Playwright render...")
            rendered = _playwright_fetch(canonical_url, deadline=deadline)
            if rendered:
                html = rendered

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
        
    return [e for e in set(emails) if is_valid_email_candidate(e)]


# Prefix noise stripped before phonenumbers.parse (e.g. "Phone: ", "Tel: ")
_PHONE_LABEL_RE = re.compile(
    r"^(?:phone|tel(?:ephone)?|call(?:\s*us)?|mob(?:ile)?|fax|contact|ph|\+?\s*)\s*[:\-]?\s*",
    re.IGNORECASE,
)

# Minimum digit count after stripping non-digits
_PHONE_MIN_DIGITS = 7
_PHONE_MAX_DIGITS = 15


def _normalize_phone(raw: str) -> str:
    """Strip label noise and collapse internal whitespace for a raw phone candidate."""
    cleaned = _PHONE_LABEL_RE.sub("", raw.strip())
    # Collapse multiple spaces/tabs to a single space
    cleaned = re.sub(r"[\t ]{2,}", " ", cleaned).strip()
    return cleaned


def extract_phone_numbers(html: str) -> list:
    """
    Extract and validate phone numbers from page HTML.

    4-stage pipeline
    ----------------
    1. Extract  — <a href="tel:..."> links (highest confidence) + regex on page text
    2. Normalize — strip label prefixes ("Phone:", "Tel:"), collapse spaces
    3. Validate  — reject dates, version strings, short/long digit runs via is_valid_phone()
    4. Deduplicate — return ordered unique list
    """
    if not html:
        return []
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception as exc:  # noqa: BLE001
        print(f"[page_extractor] HTML parse error in phone extraction: {exc}")
        return []

    raw_candidates: list[str] = []

    # ── Stage 1a: tel: href links (most reliable source) ─────────────────
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().startswith("tel:"):
            # e.g.  tel:+919876543210  or  tel:011-23456789
            num = href[4:].strip().replace("%20", " ")
            if num:
                raw_candidates.append(num)

    # ── Stage 1b: regex scan over visible text ────────────────────────────
    try:
        page_text = soup.get_text(" ")
    except Exception:
        page_text = ""
    raw_candidates.extend(PHONE_CAPTURE_PATTERN.findall(page_text))

    # ── Stages 2-4: normalize → validate → dedup ─────────────────────────
    seen: set[str] = set()
    validated: list[str] = []
    for raw in raw_candidates:
        normalized = _normalize_phone(raw)
        if not normalized:
            continue
        # Quick digit-count guard before calling is_valid_phone (cheap)
        digits = re.sub(r"\D", "", normalized)
        if len(digits) < _PHONE_MIN_DIGITS or len(digits) > _PHONE_MAX_DIGITS:
            continue
        if is_valid_phone(normalized) and normalized not in seen:
            seen.add(normalized)
            validated.append(normalized)
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


def _build_postal_address(addr: dict) -> str:
    """Build a human-readable address string from a schema.org PostalAddress dict."""
    parts = []
    for field in ("streetAddress", "addressLocality", "addressRegion", "postalCode", "addressCountry"):
        val = addr.get(field)
        if isinstance(val, dict):
            val = val.get("name") or val.get("@id") or ""
        if val and str(val).strip():
            parts.append(str(val).strip())
    return ", ".join(parts)


def extract_structured_contact_info(html: str) -> dict:
    """
    Parse JSON-LD and microdata (schema.org) from HTML.
    Returns a dict with extracted:
      emails   : list[str]
      phones   : list[str]
      location : str   — full address built from PostalAddress fields
    """
    extracted: dict = {"emails": [], "phones": [], "location": ""}
    if not html:
        return extracted

    import json
    try:
        soup = BeautifulSoup(html, "html.parser")

        # ── 1. JSON-LD blocks ────────────────────────────────────────────────
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                content = script.string
                if not content:
                    continue
                content = content.strip()
                if content.startswith("/*<![CDATA[*/"):
                    content = content.replace("/*<![CDATA[*/", "").replace("/*]]>*/", "")

                data = json.loads(content)

                def traverse(node):  # noqa: C901
                    if isinstance(node, dict):
                        for k, v in node.items():
                            kl = k.lower()
                            # email
                            if kl == "email" and isinstance(v, str):
                                clean = v.replace("mailto:", "").strip()
                                if "@" in clean:
                                    extracted["emails"].append(clean)
                            # telephone — can be string or list
                            elif kl == "telephone":
                                for item in ([v] if isinstance(v, str) else (v if isinstance(v, list) else [])):
                                    if isinstance(item, str) and item.strip():
                                        extracted["phones"].append(item.strip())
                            # address / location → PostalAddress
                            elif kl in ("address", "location", "contactpoint") and isinstance(v, dict):
                                if not extracted["location"]:
                                    built = _build_postal_address(v)
                                    if built:
                                        extracted["location"] = built
                                traverse(v)
                            else:
                                traverse(v)
                    elif isinstance(node, list):
                        for item in node:
                            traverse(item)

                traverse(data)
            except Exception:
                continue

        # ── 2. schema.org microdata (itemprop) ───────────────────────────────
        # Build postal address from itemprop fields
        addr_parts: dict[str, str] = {}
        for elem in soup.find_all(itemprop=True):
            prop = elem["itemprop"].lower()
            val = (elem.get("content") or elem.get_text()).strip()
            if prop == "email":
                clean = val.replace("mailto:", "").strip()
                if "@" in clean:
                    extracted["emails"].append(clean)
            elif prop == "telephone":
                if val:
                    extracted["phones"].append(val)
            elif prop in ("streetaddress", "addresslocality", "addressregion",
                          "postalcode", "addresscountry"):
                addr_parts[prop] = val

        if addr_parts and not extracted["location"]:
            ordered = [
                addr_parts.get("streetaddress", ""),
                addr_parts.get("addresslocality", ""),
                addr_parts.get("addressregion", ""),
                addr_parts.get("postalcode", ""),
                addr_parts.get("addresscountry", ""),
            ]
            extracted["location"] = ", ".join(p for p in ordered if p)

    except Exception as exc:
        print(f"[page_extractor] Error parsing structured contact info: {exc}")

    extracted["emails"] = [e for e in set(extracted["emails"]) if is_valid_email_candidate(e)]
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
                    
                    if is_disallowed_subpage_url(abs_url, text):
                        continue

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

            if is_disallowed_subpage_url(abs_url, text):
                if "privacy" in text or "privacy" in href_lower:
                    found["privacy_page"] = abs_url
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

# Matches "100 employees", "50-200 staff", "team of 50+", "over 100 professionals"
_EMPLOYEES_PATTERN = re.compile(
    r"(\d[\d,]*)\s*[-–+]?\s*(\d[\d,]*)?\s*"
    r"(?:employees|team\s+members|professionals|staff|headcount|workforce|consultants|experts)",
    re.IGNORECASE,
)
_EMPLOYEES_TEAM_OF = re.compile(
    r"(?:team|group|company|workforce|staff)\s+(?:of|strength\s+of)\s+(\d[\d,]*)\+?",
    re.IGNORECASE,
)
_EMPLOYEES_OVER = re.compile(
    r"(?:over|more\s+than|\+)\s*(\d[\d,]*)\s+"
    r"(?:employees|professionals|people|staff|team\s+members|consultants|experts|specialists|engineers)",
    re.IGNORECASE,
)
# "1000+ experts / 500+ certified professionals" — number first, then qualifier
_EMPLOYEES_N_PLUS = re.compile(
    r"(\d[\d,]*)[\+]\s+(?:certified\s+)?(?:employees|professionals|experts|consultants|engineers|specialists|people|staff|team\s+members)",
    re.IGNORECASE,
)
# "Our 300 consultants" / "200 certified cloud professionals"
_EMPLOYEES_PRECEDED = re.compile(
    r"(?:our|with|has|have|of)\s+(\d[\d,]*)\+?\s+(?:certified\s+)?(?:employees|professionals|experts|consultants|engineers|staff|people)",
    re.IGNORECASE,
)
# "1000 strong" / "1000-strong team"
_EMPLOYEES_STRONG = re.compile(
    r"(\d[\d,]*)\s*[-–]?strong",
    re.IGNORECASE,
)
# LinkedIn-style badge: "51-200 employees" or "1,001-5,000 employees"
_EMPLOYEES_RANGE_BADGE = re.compile(
    r"(\d[\d,]*[-–]\d[\d,]*)\s+employees",
    re.IGNORECASE,
)

_FOUNDED_PATTERN = re.compile(
    r"(?:founded|established|incorporated|since|est\.?|building\s+since)\s+(?:in\s+)?(\d{4})",
    re.IGNORECASE,
)
_COPYRIGHT_YEAR = re.compile(
    r"[©\(c\)]+\s*(\d{4})\s*[-–]",  # © 2014–2024 Company
    re.IGNORECASE,
)


def _extract_employees(text: str) -> str:
    """Extract employee count/range from page text using multiple patterns."""
    t = text or ""
    # 1. LinkedIn-style range badge: "51-200 employees" (most reliable when present)
    m = _EMPLOYEES_RANGE_BADGE.search(t)
    if m:
        return m.group(1).replace(",", "")
    # 2. "500-1000 employees", "50-200 staff", "100+ consultants"
    m = _EMPLOYEES_PATTERN.search(t)
    if m:
        lo = m.group(1).replace(",", "")
        hi = m.group(2)
        return f"{lo}-{hi.replace(',', '')}" if hi else lo
    # 3. "1000+ experts / 500+ certified professionals"
    m = _EMPLOYEES_N_PLUS.search(t)
    if m:
        return m.group(1).replace(",", "") + "+"
    # 4. "team of 50+" / "team strength of 500"
    m = _EMPLOYEES_TEAM_OF.search(t)
    if m:
        return m.group(1).replace(",", "") + "+"
    # 5. "over 100 employees" / "more than 500 experts"
    m = _EMPLOYEES_OVER.search(t)
    if m:
        return m.group(1).replace(",", "") + "+"
    # 6. "Our 300 consultants" / "200 certified cloud professionals"
    m = _EMPLOYEES_PRECEDED.search(t)
    if m:
        return m.group(1).replace(",", "")
    # 7. "1000 strong" / "1000-strong team"
    m = _EMPLOYEES_STRONG.search(t)
    if m:
        return m.group(1).replace(",", "")
    return None


def _extract_employees_from_jsonld(html: str) -> str | None:
    """Parse JSON-LD numberOfEmployees (integer, string, or QuantitativeValue)."""
    try:
        import json as _json
        from bs4 import BeautifulSoup as _BS
        soup = _BS(html, "html.parser")
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = _json.loads(script.string or "")

                def _seek_emp(node):
                    if isinstance(node, dict):
                        val = node.get("numberOfEmployees")
                        if val is not None:
                            if isinstance(val, (int, float)):
                                return str(int(val))
                            if isinstance(val, str) and val.strip():
                                return val.strip()
                            if isinstance(val, dict):  # QuantitativeValue
                                v = val.get("value") or val.get("minValue")
                                max_v = val.get("maxValue")
                                if v and max_v:
                                    return f"{v}-{max_v}"
                                if v:
                                    return str(v)
                        for v in node.values():
                            r = _seek_emp(v)
                            if r:
                                return r
                    elif isinstance(node, list):
                        for item in node:
                            r = _seek_emp(item)
                            if r:
                                return r
                    return None

                found = _seek_emp(data)
                if found:
                    return found
            except Exception:
                continue
    except Exception:
        pass
    return None


def _extract_founded(html: str) -> str:
    """Extract founding year from JSON-LD, visible text, or footer copyright."""
    # 1. JSON-LD: foundingYear / foundingDate / establishmentDate / copyrightYear
    try:
        import json as _json
        from bs4 import BeautifulSoup as _BS
        soup = _BS(html, "html.parser")
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = _json.loads(script.string or "")

                def _seek(node):  # noqa: C901
                    if isinstance(node, dict):
                        for k, v in node.items():
                            if k.lower() in (
                                "foundingyear", "foundingdate",
                                "establishmentdate", "copyrightyear",
                            ) and v:
                                year = str(v)[:4]
                                if year.isdigit() and 1800 <= int(year) <= 2100:
                                    return year
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
                if found:
                    return found
            except Exception:
                continue
    except Exception:
        pass
    # 2. Regex on plain text ("founded in 2012", "Est. 2015", "since 2018")
    try:
        from bs4 import BeautifulSoup as _BS
        text = _BS(html, "html.parser").get_text(" ")
        m = _FOUNDED_PATTERN.search(text)
        if m:
            yr = m.group(1)
            if 1800 <= int(yr) <= 2100:
                return yr
    except Exception:
        pass
    # 3. Footer copyright year: "© 2014–2024" → founded 2014
    try:
        from bs4 import BeautifulSoup as _BS
        soup = _BS(html, "html.parser")
        footer_elems = soup.find_all(["footer", "div"], limit=20)
        for elem in footer_elems:
            cls = " ".join(elem.get("class") or [])
            if any(k in cls.lower() for k in ("footer", "bottom", "copyright")):
                ft = elem.get_text(" ")
                m = _COPYRIGHT_YEAR.search(ft)
                if m:
                    yr = m.group(1)
                    if 1800 <= int(yr) <= 2100:
                        return yr
    except Exception:
        pass
    return None


# Common country name / code keywords for footer address scanning
_COUNTRY_KEYWORDS = {
    "india": "India", "usa": "USA", "united states": "USA",
    "united kingdom": "UK", "uk": "UK", "germany": "Germany",
    "canada": "Canada", "australia": "Australia", "singapore": "Singapore",
    "netherlands": "Netherlands", "france": "France", "spain": "Spain",
    "italy": "Italy", "brazil": "Brazil", "japan": "Japan",
    "china": "China", "south africa": "South Africa", "uae": "UAE",
    "united arab emirates": "UAE",
}
# TLD → country fallback
_TLD_COUNTRY = {
    ".in": "India", ".co.in": "India", ".co.uk": "UK", ".uk": "UK",
    ".de": "Germany", ".ca": "Canada", ".au": "Australia",
    ".sg": "Singapore", ".nl": "Netherlands", ".fr": "France",
    ".es": "Spain", ".it": "Italy", ".br": "Brazil", ".jp": "Japan",
    ".cn": "China", ".ae": "UAE", ".za": "South Africa",
}


def _extract_country(html: str, page_url: str = "") -> str:
    """Extract country from JSON-LD, meta geo-tags, itemprop, footer address, or TLD."""
    try:
        import json as _json
        from bs4 import BeautifulSoup as _BS
        soup = _BS(html, "html.parser")

        # 1. JSON-LD addressCountry
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = _json.loads(script.string or "")

                def _seek_country(node):  # noqa: C901
                    if isinstance(node, dict):
                        addr = node.get("address") or {}
                        if isinstance(addr, dict):
                            country = addr.get("addressCountry") or addr.get("country")
                            if country:
                                if isinstance(country, dict):
                                    country = country.get("name") or country.get("@id") or ""
                                return str(country).strip()
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

        # 2. Meta geo tags: <meta name="geo.country" content="IN">
        for meta in soup.find_all("meta"):
            name = (meta.get("name") or meta.get("property") or "").lower()
            if name in ("geo.country", "geo.region", "og:country-name",
                        "country", "dc.coverage"):
                val = (meta.get("content") or "").strip()
                if val:
                    return val

        # 3. itemprop="addressCountry"
        for elem in soup.find_all(itemprop="addressCountry"):
            v = (elem.get("content") or elem.get_text()).strip()
            if v:
                return v

        # 4. Footer address text scan for known country names
        page_text = soup.get_text(" ").lower()
        for kw, label in _COUNTRY_KEYWORDS.items():
            # Look for country near address-like context
            idx = page_text.find(kw)
            if idx != -1:
                context = page_text[max(0, idx - 80): idx + len(kw) + 80]
                if any(c in context for c in (
                    "address", "office", "headquarter", "located",
                    "phone", "contact", "street", "avenue", "road", "pin", "zip",
                )):
                    return label

    except Exception:
        pass

    # 5. TLD fallback (cheapest — no parsing needed)
    if page_url:
        from urllib.parse import urlparse as _up
        netloc = _up(page_url).netloc.lower()
        for tld, label in sorted(_TLD_COUNTRY.items(), key=lambda x: -len(x[0])):
            if netloc.endswith(tld):
                return label

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Main extraction entry-point  (Tasks 5, 6, 7 + new profile fields)
# ─────────────────────────────────────────────────────────────────────────────

def extract_from_website(homepage_url: str, homepage_html: str | None = None, deadline: Deadline | None = None) -> dict:
    """
    Full public-data extraction pass:
    homepage → contact/about/team/services/products subpages
             → emails, phones, socials, people.
    """
    if deadline and deadline.is_exceeded():
        raise DeadlineExceeded(f"Deadline exceeded before extract_from_website for {homepage_url}")

    result = {
        "contact_page":      None,
        "about_page":        None,
        "team_page":         None,
        "services_page":     None,
        "products_page":     None,
        "emails":            [],
        "emails_provenance": [],
        "emails_scored":     [],
        "phones":            [],
        "phones_provenance": [],
        "social_links":      {},
        "people":            [],
        "company_type":      "Unknown",
        "industry_detected": "Unknown",
        "meta_description":  "",
        "tech_stack":        [],
        "employees":         None,
        "employees_provenance": None,
        "founded":           None,
        "founded_provenance":   None,
        "country":           None,
        "country_provenance":   None,
        "location":          None,   # full postal address string (new)
        "location_provenance":  None,
        "description":       None,
    }

    from urllib.parse import urlparse
    domain = urlparse(homepage_url).netloc.lower()
    state = _get_domain_budget_state(domain)
    state["pages_crawled"] = 0
    state["bytes_downloaded"] = 0
    state["start_time"] = time.time()

    if not homepage_html:
        try:
            homepage_html = fetch_page(homepage_url, deadline=deadline)
        except DeadlineExceeded:
            print(f"[page_extractor] Deadline exceeded fetching homepage {homepage_url}")
            return result
    else:
        # Pre-fetched homepage: record it as 1 page and estimate size
        state["pages_crawled"] = 1
        state["bytes_downloaded"] = len(homepage_html.encode("utf-8") if isinstance(homepage_html, str) else homepage_html)

    if not homepage_html:
        return result

    # ── Homepage pass ─────────────────────────────────────────────────────
    result["social_links"] = extract_social_links(homepage_html, homepage_url)
    
    hp_emails = extract_emails(homepage_html)
    result["emails"].extend(hp_emails)
    for em in hp_emails:
        result["emails_provenance"].append(make_fact(em, SRC_HOMEPAGE_TEXT, source_url=homepage_url))

    hp_phones = extract_phone_numbers(homepage_html)
    result["phones"].extend(hp_phones)
    for ph in hp_phones:
        result["phones_provenance"].append(make_fact(ph, SRC_HOMEPAGE_TEXT, source_url=homepage_url))

    # Extract structured contact info from homepage (emails, phones, location)
    struct_info = extract_structured_contact_info(homepage_html)
    result["emails"].extend(struct_info["emails"])
    for em in struct_info["emails"]:
        result["emails_provenance"].append(make_fact(em, SRC_HOMEPAGE_STRUCTURED, source_url=homepage_url))

    result["phones"].extend(struct_info["phones"])
    for ph in struct_info["phones"]:
        result["phones_provenance"].append(make_fact(ph, SRC_HOMEPAGE_STRUCTURED, source_url=homepage_url))

    if struct_info.get("location") and not result["location"]:
        result["location"] = struct_info["location"]
        result["location_provenance"] = make_fact(struct_info["location"], SRC_JSON_LD_HOMEPAGE, source_url=homepage_url)

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
    # Employees: JSON-LD first (most reliable), then text regex
    _emp_ld = _extract_employees_from_jsonld(homepage_html)
    if _emp_ld:
        result["employees"] = _emp_ld
        result["employees_provenance"] = make_fact(_emp_ld, SRC_JSON_LD_HOMEPAGE, source_url=homepage_url)
    else:
        _emp_txt = _extract_employees(hp_text)
        if _emp_txt:
            result["employees"] = _emp_txt
            result["employees_provenance"] = make_fact(_emp_txt, SRC_HOMEPAGE_TEXT, source_url=homepage_url)

    _fnd = _extract_founded(homepage_html)
    if _fnd:
        result["founded"] = _fnd
        result["founded_provenance"] = make_fact(_fnd, SRC_HOMEPAGE_STRUCTURED, source_url=homepage_url)

    _cntry = _extract_country(homepage_html, homepage_url)
    if _cntry:
        result["country"] = _cntry
        result["country_provenance"] = make_fact(_cntry, SRC_META_GEO_TAG, source_url=homepage_url)
    # Description: prefer meta text; fall back to first substantial <p> on the page
    if meta_text and len(meta_text.strip()) > 40:
        result["description"] = meta_text[:800]
    else:
        try:
            from bs4 import BeautifulSoup as _BS
            _soup = _BS(homepage_html, "html.parser")
            for p in _soup.find_all("p"):
                txt = p.get_text(" ", strip=True)
                if len(txt) > 80:
                    result["description"] = txt[:800]
                    break
        except Exception:
            pass

    # ── People from homepage (founders, CEOs listed on homepage) ─────────
    result["people"].extend(extract_people(homepage_html))

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
        for cand in ("/corporate/contact-us/", "/contact-us/", "/contact/"):
            cand_url = urljoin(homepage_url, cand)
            if not is_disallowed_subpage_url(cand_url):
                result["contact_page"] = cand_url
                break
    if not result["about_page"]:
        for cand in ("/corporate/", "/about-us/", "/about/"):
            cand_url = urljoin(homepage_url, cand)
            if not is_disallowed_subpage_url(cand_url):
                result["about_page"] = cand_url
                break

    # ── Consolidate pages to crawl ────────────────────────────────────────
    pages_to_scrape: dict[str, str] = {}
    for page_type in ("contact_page", "about_page", "team_page",
                      "services_page", "products_page"):
        url = result[page_type]
        if url and not is_disallowed_subpage_url(url):
            pages_to_scrape[url] = page_type

    # Follow footer contact/about links (limit to 2 extra)
    footer_links = find_footer_links(homepage_html, homepage_url)
    extra_crawled = 0
    for link in footer_links:
        if link not in pages_to_scrape and extra_crawled < 2:
            if not is_disallowed_subpage_url(link):
                pages_to_scrape[link] = "footer_link"
                extra_crawled += 1

    # ── Sub-page passes ───────────────────────────────────────────────────
    for url, page_type in pages_to_scrape.items():
        if deadline and deadline.is_exceeded():
            break
        try:
            html = fetch_page(url, deadline=deadline)
        except DeadlineExceeded:
            break
        if not html:
            continue

        # 1. Standard text-based extraction
        txt_src = SRC_CONTACT_PAGE_TEXT if page_type == "contact_page" else (
            SRC_ABOUT_PAGE_TEXT if page_type == "about_page" else f"{page_type}_text"
        )
        sub_emails = extract_emails(html)
        result["emails"].extend(sub_emails)
        for em in sub_emails:
            result["emails_provenance"].append(make_fact(em, txt_src, source_url=url))

        sub_phones = extract_phone_numbers(html)
        result["phones"].extend(sub_phones)
        for ph in sub_phones:
            result["phones_provenance"].append(make_fact(ph, txt_src, source_url=url))

        # 2. Structured JSON-LD / microdata extraction
        st_src = SRC_CONTACT_PAGE_STRUCTURED if page_type == "contact_page" else (
            SRC_ABOUT_PAGE_STRUCTURED if page_type == "about_page" else SRC_JSON_LD_SUBPAGE
        )
        sub_struct = extract_structured_contact_info(html)
        result["emails"].extend(sub_struct["emails"])
        for em in sub_struct["emails"]:
            result["emails_provenance"].append(make_fact(em, st_src, source_url=url))

        result["phones"].extend(sub_struct["phones"])
        for ph in sub_struct["phones"]:
            result["phones_provenance"].append(make_fact(ph, st_src, source_url=url))

        # Merge location (first non-empty wins)
        if sub_struct.get("location") and not result["location"]:
            result["location"] = sub_struct["location"]
            result["location_provenance"] = make_fact(sub_struct["location"], SRC_JSON_LD_SUBPAGE, source_url=url)
        # Also merge social links from sub-pages
        for platform, purl in extract_social_links(html, homepage_url).items():
            if platform not in result["social_links"]:
                result["social_links"][platform] = purl

        # Improve enrichment if about/services page has more content
        if page_type in ("about_page", "services_page", "products_page"):
            page_meta = extract_meta_text(html)
            if result["industry_detected"] == "Unknown":
                result["industry_detected"] = detect_industry(page_meta)
            if result["company_type"] == "Unknown":
                result["company_type"] = detect_company_type(page_meta)
            # Richer description from about page
            if page_type == "about_page" and not result["description"]:
                if page_meta and len(page_meta.strip()) > 40:
                    result["description"] = page_meta[:800]
                else:
                    try:
                        from bs4 import BeautifulSoup as _BS
                        _asoup = _BS(html, "html.parser")
                        for p in _asoup.find_all("p"):
                            txt = p.get_text(" ", strip=True)
                            if len(txt) > 80:
                                result["description"] = txt[:800]
                                break
                    except Exception:
                        pass
            # Profile fields from about page (override blanks) — JSON-LD first
            if not result["employees"]:
                sub_emp_ld = _extract_employees_from_jsonld(html)
                if sub_emp_ld:
                    result["employees"] = sub_emp_ld
                    result["employees_provenance"] = make_fact(sub_emp_ld, SRC_JSON_LD_SUBPAGE, source_url=url)
            if not result["employees"]:
                try:
                    from bs4 import BeautifulSoup as _BS
                    pg_text = _BS(html, "html.parser").get_text(" ")
                    sub_emp_txt = _extract_employees(pg_text)
                    if sub_emp_txt:
                        result["employees"] = sub_emp_txt
                        result["employees_provenance"] = make_fact(sub_emp_txt, SRC_ABOUT_PAGE_TEXT, source_url=url)
                except Exception:
                    pass
            if not result["founded"]:
                sub_fnd = _extract_founded(html)
                if sub_fnd:
                    result["founded"] = sub_fnd
                    result["founded_provenance"] = make_fact(sub_fnd, SRC_ABOUT_PAGE_STRUCTURED, source_url=url)
            if not result["country"]:
                sub_cntry = _extract_country(html, url)
                if sub_cntry:
                    result["country"] = sub_cntry
                    result["country_provenance"] = make_fact(sub_cntry, SRC_META_GEO_TAG, source_url=url)

        # People: run on about_page AND team_page (many companies list founders on /about)
        if page_type in ("team_page", "about_page"):
            result["people"].extend(extract_people(html))

    # ── Final dedup + ranking ─────────────────────────────────────────────
    result["emails"] = rank_emails(result["emails"])
    seen_em_prov = set()
    deduped_em_prov = []
    for ep in result["emails_provenance"]:
        val = ep.get("value")
        if val and val in result["emails"] and val not in seen_em_prov:
            seen_em_prov.add(val)
            deduped_em_prov.append(ep)
    result["emails_provenance"] = deduped_em_prov

    # Deduplicate phones: also run through normalize+validate again to catch
    # raw JSON-LD strings that bypassed the 4-stage pipeline in extract_phone_numbers
    seen_phones: set[str] = set()
    clean_phones: list[str] = []
    for ph in result["phones"]:
        n = _normalize_phone(ph)
        digits = re.sub(r"\D", "", n)
        if len(digits) < _PHONE_MIN_DIGITS or len(digits) > _PHONE_MAX_DIGITS:
            continue
        if is_valid_phone(n) and n not in seen_phones:
            seen_phones.add(n)
            clean_phones.append(n)
    result["phones"] = sorted(clean_phones)

    seen_ph_prov = set()
    deduped_ph_prov = []
    for pp in result["phones_provenance"]:
        n_val = _normalize_phone(pp.get("value", ""))
        if n_val in result["phones"] and n_val not in seen_ph_prov:
            seen_ph_prov.add(n_val)
            pp_copy = dict(pp)
            pp_copy["value"] = n_val
            deduped_ph_prov.append(pp_copy)
    result["phones_provenance"] = deduped_ph_prov

    # Fallback: if location still empty, use country field
    if not result["location"] and result["country"]:
        result["location"] = result["country"]
        result["location_provenance"] = result.get("country_provenance")

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

