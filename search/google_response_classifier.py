import re
import hashlib
import logging
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

def classify_google_response(html: str, status_code: int, url: str) -> dict:
    """
    Analyzes a Google HTML response and returns a dictionary with:
    - page_type (str)
    - confidence_score (float)
    - detected_signals (list of str)
    - title (str)
    - language (str)
    - content_length (int)
    - layout_fingerprint (str)
    """
    result = {
        "page_type": "UNKNOWN_LAYOUT",
        "confidence_score": 0.5,
        "detected_signals": [],
        "title": "Unknown Title",
        "language": "en",
        "content_length": len(html) if html else 0,
        "layout_fingerprint": "00000000000000000000000000000000"
    }

    if not html:
        result["page_type"] = "EMPTY_SERP"
        result["confidence_score"] = 1.0
        result["detected_signals"].append("Empty HTML payload")
        return result

    soup = BeautifulSoup(html, "html.parser")
    
    # Extract Title
    title_el = soup.find("title")
    title = title_el.get_text(" ", strip=True) if title_el else "No Title Tag"
    result["title"] = title

    # Extract Language
    html_tag = soup.find("html")
    lang = html_tag.get("lang", "en") if html_tag else "en"
    result["language"] = lang

    # Calculate HTML Fingerprint
    classes = set()
    for el in soup.find_all(class_=True):
        for c in el.get("class", []):
            if c:
                classes.add(c)
    top_classes = sorted(list(classes))[:20]
    elements_count = len(soup.find_all())
    
    fingerprint_str = f"title:{title}||classes:{','.join(top_classes)}||elements:{elements_count}"
    result["layout_fingerprint"] = hashlib.md5(fingerprint_str.encode('utf-8')).hexdigest()

    html_lower = html.lower()
    url_lower = url.lower()
    signals = []

    # 0. Menlo Security proxy interception
    menlo_terms = ["menlo.gutsenv.net", "safeview", "menlosecurity", "menlo security", "sv_role="]
    matched_menlo = [t for t in menlo_terms if t in html_lower]
    if matched_menlo or "menlo.gutsenv.net" in url_lower:
        result["page_type"] = "CAPTCHA_PAGE"
        result["confidence_score"] = 0.99
        result["detected_signals"] = ["Menlo Security safeview proxy intercept"]
        return result

    # 1. CAPTCHA detection
    captcha_terms = ["g-recaptcha", "hcaptcha", "recaptcha", "i'm not a robot", "showcaptcha", "captcha-form", "security check"]
    matched_captcha = [t for t in captcha_terms if t in html_lower]
    if matched_captcha:
        result["page_type"] = "CAPTCHA_PAGE"
        result["confidence_score"] = 0.99
        result["detected_signals"] = matched_captcha
        return result

    # 2. Sorry Page (anti-bot / 429) detection
    sorry_terms = ["our systems have detected unusual traffic", "unusual traffic from your computer network", "sorry/index.html", "unusual traffic"]
    matched_sorry = [t for t in sorry_terms if t in html_lower]
    if status_code == 429 or "/sorry/" in url_lower or matched_sorry:
        result["page_type"] = "SORRY_PAGE"
        result["confidence_score"] = 0.99
        result["detected_signals"] = matched_sorry or ["HTTP 429 or /sorry/ redirect"]
        return result

    # 3. Consent Page detection
    consent_terms = ["before you continue to google", "consent.google", "accept all", "cookie consent", "agree before you continue"]
    matched_consent = [t for t in consent_terms if t in html_lower]
    if "consent.google" in url_lower or matched_consent:
        result["page_type"] = "CONSENT_PAGE"
        result["confidence_score"] = 0.98
        result["detected_signals"] = matched_consent or ["consent.google domain redirect"]
        return result

    # 4. Enable JS detection
    enable_js_terms = ["/httpservice/retry/enablejs", "enablejs", "javascript required", "please click here", "enable javascript"]
    matched_js = [t for t in enable_js_terms if t in html_lower]
    if matched_js:
        result["page_type"] = "ENABLE_JS_PAGE"
        result["confidence_score"] = 0.95
        result["detected_signals"] = matched_js
        return result

    # 5. Login Page detection
    login_terms = ["accounts.google.com/login", "sign in - google accounts", "log in to your account", "google login"]
    matched_login = [t for t in login_terms if t in html_lower]
    if "accounts.google" in url_lower or matched_login:
        result["page_type"] = "LOGIN_PAGE"
        result["confidence_score"] = 0.95
        result["detected_signals"] = matched_login or ["Google Login URL Redirect"]
        return result

    # 6. Zero Results detection
    zero_terms = ["did not match any documents", "no results found for", "did not match any search results", "no organic results matched"]
    matched_zero = [t for t in zero_terms if t in html_lower]
    if matched_zero:
        result["page_type"] = "ZERO_RESULTS_PAGE"
        result["confidence_score"] = 0.99
        result["detected_signals"] = matched_zero
        return result

    # 7. AI Overview Page detection
    ai_terms = ["ai overview", "generative ai", "google ai reference", "super-overview"]
    matched_ai = [t for t in ai_terms if t in html_lower]
    if matched_ai:
        signals.extend(matched_ai)
        result["page_type"] = "AI_OVERVIEW_PAGE"
        result["confidence_score"] = 0.90

    # 8. Knowledge Panel detection
    kp_terms = ["knowledge panel", "kp-blk", "kno-vrt-g", "kp-header"]
    matched_kp = [t for t in kp_terms if t in html_lower]
    if matched_kp:
        signals.extend(matched_kp)
        if result["page_type"] == "UNKNOWN_LAYOUT":
            result["page_type"] = "KNOWLEDGE_PANEL_PAGE"
            result["confidence_score"] = 0.90

    # 9. Featured Snippet detection
    snippet_terms = ["featured snippet", "class=\"c2xz6d\"", "class=\"kp-header\""]
    matched_snippet = [t for t in snippet_terms if t in html_lower]
    if matched_snippet:
        signals.extend(matched_snippet)
        if result["page_type"] == "UNKNOWN_LAYOUT":
            result["page_type"] = "FEATURED_SNIPPET_PAGE"
            result["confidence_score"] = 0.85

    # 10. People Also Ask detection
    paa_terms = ["people also ask", "related-question-pair", "class=\"yo340b\""]
    matched_paa = [t for t in paa_terms if t in html_lower]
    if matched_paa:
        signals.extend(matched_paa)
        if result["page_type"] == "UNKNOWN_LAYOUT":
            result["page_type"] = "PEOPLE_ALSO_ASK_PAGE"
            result["confidence_score"] = 0.85

    # 11. Localized TLD detection
    if "google.co." in url_lower or "google.com." in url_lower:
        signals.append("Localized TLD redirect")
        if result["page_type"] == "UNKNOWN_LAYOUT":
            result["page_type"] = "LOCALIZED_SERP"
            result["confidence_score"] = 0.80

    # 12. Desktop vs Mobile normal SERP
    organic_indicators = [
        "id=\"search\"", "class=\"g\"", "/url?q=", "class=\"r\"",
        "id=\"main\"", "class=\"v7w49e\"", "data-hveid",
        "class=\"tF2Cxc\"", "class=\"yuRUbf\"", "class=\"MjjYud\"",
        "class=\"N54PNb\""
    ]
    matched_organic = [t for t in organic_indicators if t in html_lower]
    if matched_organic:
        signals.extend(matched_organic)
        if "viewport" in html_lower and ("mobile" in html_lower or "android" in html_lower):
            result["page_type"] = "NORMAL_MOBILE_SERP"
            result["confidence_score"] = 0.90
        else:
            result["page_type"] = "NORMAL_DESKTOP_SERP"
            result["confidence_score"] = 0.95

    # If UNKNOWN_LAYOUT but has any signals, promote to NORMAL_DESKTOP_SERP
    # (parsers ran on a real SERP but didn't match — parser issue, not unknown page)
    if result["page_type"] == "UNKNOWN_LAYOUT" and signals:
        result["page_type"] = "NORMAL_DESKTOP_SERP"
        result["confidence_score"] = 0.70

    # Final signal: even with no class matches, id="search" strongly implies SERP
    if result["page_type"] == "UNKNOWN_LAYOUT" and ('id="search"' in html or "id='search'" in html):
        result["page_type"] = "NORMAL_DESKTOP_SERP"
        result["confidence_score"] = 0.75
        signals.append("id=search present")

    result["detected_signals"] = signals
    return result
