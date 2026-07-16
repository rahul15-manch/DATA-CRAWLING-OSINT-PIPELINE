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

def _fetch_homepage(url: str) -> str:
    """Fetch homepage HTML. Tries direct first, then 1 proxy retry."""
    if not url.startswith("http"):
        url = "https://" + url
        
    # Try direct connection
    direct_req = Request(
        url=url,
        method="GET",
        timeout=8.0,
        meta={"proxy_strategy": "direct", "bypass_proxy": True, "provider": "homepage_evaluator"}
    )
    
    try:
        resp = _client.send_request(direct_req)
        if resp.status_code in (200, 301, 302, 307, 308):
            return resp.text
        if resp.status_code not in (403, 429, 401):
            return "" # Don't retry for 404, 500, etc.
    except Exception as e:
        # Connection reset, timeout, etc. -> fallback
        pass
        
    # Proxy fallback (strict proxy, do not double-try direct)
    proxy_req = Request(
        url=url,
        method="GET",
        timeout=10.0,
        meta={"provider": "homepage_evaluator", "require_proxy": True} 
    )
    try:
        resp = _client.send_request(proxy_req)
        if resp.status_code == 200:
            return resp.text
    except Exception:
        pass
        
    return ""

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
