"""
discovery/homepage_evaluator.py
===============================
Lightweight crawler to evaluate UNKNOWN company homepages.
Uses a direct connection first, falling back to one proxy retry if blocked.
Scans DOM for business signals.
"""

import time
from bs4 import BeautifulSoup
from network_client_project.network.client import NetworkClient
from network_client_project.network.middleware.base import Request
from curl_cffi.requests.exceptions import RequestException

# Initialize a separate client instance if needed, or use a global one
# For simplicity, we just instantiate one
_client = NetworkClient()

def _is_real_html(resp) -> bool:
    """
    Returns True only if the response looks like real HTML content.
    Rejects:
      - Non-HTML content types (JSON, XML, PDF, binary, etc.)
      - WAF / anti-bot challenge pages (Cloudflare, Akamai, reCAPTCHA)
    """
    content_type = (resp.headers.get("Content-Type") or resp.headers.get("content-type") or "").lower()
    html_types = ("text/html", "application/xhtml")
    if not any(ct in content_type for ct in html_types):
        return False

    # Challenge page detection: real homepages don't have these markers
    text_lower = (resp.text or "")[:4096].lower()
    challenge_markers = (
        "cf-browser-verification",
        "just a moment",
        "enable javascript and cookies to continue",
        "/_cf/",
        "challenge-platform",
        "ddos-guard",
        "perimeterx",
        "px-captcha",
        "window._cf_chl",
        "challenge-error-title",
        "recaptcha",
    )
    if any(marker in text_lower for marker in challenge_markers):
        return False

    return True


import threading

_eval_domain_consecutive_blocks = {}
_eval_domain_cooldowns = {}
_eval_cb_lock = threading.Lock()

def _fetch_homepage(url: str) -> str:
    """Fetch homepage HTML. Tries direct first, then 1 proxy retry."""
    if not url.startswith("http"):
        url = "https://" + url

    from urllib.parse import urlparse
    domain_key = urlparse(url).netloc.lower().lstrip("www.")

    from utils.deadline import Deadline
    if Deadline.is_exceeded():
        print(f"[_fetch_homepage] Global deadline exceeded for {url}. Skipping.")
        return ""

    # Check circuit breaker
    with _eval_cb_lock:
        cooldown_until = _eval_domain_cooldowns.get(domain_key, 0.0)
        if time.time() < cooldown_until:
            return ""

    success = False
    html_content = ""

    # Try direct connection
    direct_req = Request(
        url=url,
        method="GET",
        timeout=8.0,
        meta={"proxy_strategy": "direct", "bypass_proxy": True, "provider": "homepage_evaluator"}
    )

    try:
        resp = _client.send_request(direct_req)
        if resp.status_code == 404:
            print(f"[_fetch_homepage] 404 Not Found for {url}. Direct fail, no retry.")
            return ""
        if resp.status_code in (200, 301, 302, 307, 308):
            if _is_real_html(resp):
                success = True
                html_content = resp.text
            # Got a response but it's a challenge page or non-HTML — try proxy
    except Exception:
        pass

    if not success:
        # Proxy fallback (try up to 3 different unique proxies on block/failure)
        exclude_urls = set()
        
        for attempt in range(1, 4):
            if Deadline.is_exceeded():
                print(f"[_fetch_homepage] Global deadline exceeded for {url} before attempt {attempt}. Aborting.")
                break

            session_id = f"homepage_fetch_{domain_key}_{attempt}"
            proxy_req = Request(
                url=url,
                method="GET",
                timeout=12.0,
                meta={
                    "provider": "homepage_evaluator",
                    "require_proxy": True,
                    "session_id": session_id,
                    "exclude_urls": exclude_urls
                }
            )
            try:
                resp = _client.send_request(proxy_req)
                if resp.status_code == 404:
                    print(f"[_fetch_homepage] 404 Not Found for {url} via proxy. Fail fast, no retry.")
                    return ""
                proxy_used = getattr(resp, "proxy", None) or resp.request.meta.get("_proxy_obj")
                if proxy_used:
                    raw_url = getattr(proxy_used, "raw_url", proxy_used)
                    exclude_urls.add(raw_url)
                    
                if resp.status_code == 200 and _is_real_html(resp):
                    success = True
                    html_content = resp.text
                    break
            except Exception:
                pass

    # Handle success/failure transitions for Directory/Listing Domain Circuit Breaker
    if not success:
        with _eval_cb_lock:
            blocks = _eval_domain_consecutive_blocks.get(domain_key, 0) + 1
            _eval_domain_consecutive_blocks[domain_key] = blocks
            if blocks >= 10:
                _eval_domain_cooldowns[domain_key] = time.time() + 1200.0  # 20 minutes cooldown
                print(f"[EvalCircuitBreaker] Directory domain {domain_key} hit 10 consecutive blocks. Circuit opened for 20 minutes.")
    else:
        with _eval_cb_lock:
            _eval_domain_consecutive_blocks[domain_key] = 0

    return html_content

def evaluate_homepage(url: str) -> int:
    """
    Score a homepage based on business signals.
    >= 80: ALLOW
    50-79: LIKELY_COMPANY
    < 50: REJECT
    """
    if not url:
        return 0
        
    html = _fetch_homepage(url)
    if not html:
        return 0
        
    soup = BeautifulSoup(html, "html.parser")
    score = 0
    
    # 1. Look for explicit structural signals in links
    links = [a.get("href", "").lower() for a in soup.find_all("a") if a.get("href")]
    link_text = [a.get_text().lower() for a in soup.find_all("a")]
    
    signals = {
        "contact": 20,
        "about": 15,
        "services": 15,
        "products": 15,
        "careers": 15,
        "privacy": 10,
        "linkedin.com/company/": 20,
    }
    
    # Check text or hrefs
    for link, text in zip(links, link_text):
        if "contact" in text or "contact" in link:
            if signals["contact"] > 0:
                score += signals["contact"]
                signals["contact"] = 0
        if "about" in text or "about" in link:
            if signals["about"] > 0:
                score += signals["about"]
                signals["about"] = 0
        if "services" in text or "services" in link:
            if signals["services"] > 0:
                score += signals["services"]
                signals["services"] = 0
        if "products" in text or "products" in link:
            if signals["products"] > 0:
                score += signals["products"]
                signals["products"] = 0
        if "careers" in text or "careers" in link:
            if signals["careers"] > 0:
                score += signals["careers"]
                signals["careers"] = 0
        if "privacy" in text or "privacy" in link:
            if signals["privacy"] > 0:
                score += signals["privacy"]
                signals["privacy"] = 0
        if "linkedin.com/company/" in link:
            if signals["linkedin.com/company/"] > 0:
                score += signals["linkedin.com/company/"]
                signals["linkedin.com/company/"] = 0

    # 2. Extract visible text for basic signals (email, phone, copyright)
    body_text = soup.get_text().lower()
    
    if "copyright" in body_text or "©" in body_text:
        score += 10
        
    # Phone or email presence heuristic
    import re
    if re.search(r'[\w\.-]+@[\w\.-]+\.\w+', body_text):
        score += 20
        
    if re.search(r'\+?\d{1,3}[-.\s]?\(?\d{2,3}\)?[-.\s]?\d{3}[-.\s]?\d{4}', body_text):
        score += 15

    return min(100, score)
