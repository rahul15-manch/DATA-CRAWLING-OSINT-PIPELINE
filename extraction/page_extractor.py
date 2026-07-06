"""
Extracts publicly visible information from a company's own website:
emails, phone numbers, social links, contact/about/team page URLs,
and a best-effort list of named people with designations.

Hard boundary: this module only reads whatever HTML a plain GET request
returns. It does not log in, does not solve CAPTCHAs, does not bypass
robots.txt-style access controls, and does not paginate through anything
requiring auth. If a page needs a login to see, this module simply won't
see it — that's by design, not a limitation to work around.
"""

import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import config

EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_PATTERN = re.compile(r"\+?\d[\d\-.\s]{6,14}\d")

SOCIAL_DOMAINS = ["linkedin.com", "twitter.com", "x.com", "facebook.com", "instagram.com"]

PAGE_KEYWORDS = {
    "contact_page": ["contact"],
    "about_page": ["about"],
    "team_page": ["team", "people", "leadership", "founders"],
}

DESIGNATION_KEYWORDS = [
    "founder", "co-founder", "ceo", "cto", "coo", "director",
    "head of", "vp ", "president",
]

ACRONYMS = {"ceo", "cto", "coo", "vp"}


def _format_designation(kw: str) -> str:
    kw = kw.strip()
    if kw.lower() in ACRONYMS:
        return kw.upper()
    return kw.title()


def fetch_page(url: str):
    """
    Fetches a page's public HTML via a plain GET. Returns None on any
    failure. No retries, no proxy rotation here — that resilience layer
    belongs to Pillar 3, this module just reads what's freely served.
    """
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; FlowizLeadBot/1.0)"}
        resp = requests.get(url, headers=headers, timeout=config.REQUEST_TIMEOUT)
        if resp.status_code == 200:
            return resp.text
    except requests.RequestException as e:
        print(f"[page_extractor] failed to fetch {url}: {e}")
    return None


def extract_emails(html: str) -> list:
    if not html:
        return []
    return sorted(set(EMAIL_PATTERN.findall(html)))


def extract_phone_numbers(html: str) -> list:
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ")
    candidates = PHONE_PATTERN.findall(text)
    cleaned = []
    for c in candidates:
        digits = re.sub(r"\D", "", c)
        if len(digits) >= 7:  # crude filter to drop years, zip codes etc.
            cleaned.append(c.strip())
    return sorted(set(cleaned))


def extract_social_links(html: str, base_url: str) -> dict:
    if not html:
        return {}
    soup = BeautifulSoup(html, "html.parser")
    links = {}
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        domain = urlparse(href).netloc.lower()
        for social in SOCIAL_DOMAINS:
            if social in domain and social not in links:
                links[social] = href
    return links


def find_subpages(html: str, base_url: str) -> dict:
    """Scans the homepage's own links for contact/about/team pages."""
    if not html:
        return {}
    soup = BeautifulSoup(html, "html.parser")
    found = {}
    for a in soup.find_all("a", href=True):
        text = (a.get_text() or "").lower()
        href = a["href"].lower()
        for page_type, keywords in PAGE_KEYWORDS.items():
            if page_type in found:
                continue
            if any(kw in text or kw in href for kw in keywords):
                found[page_type] = urljoin(base_url, a["href"])
    return found


def extract_people(html: str) -> list:
    """
    Best-effort extraction of (name, designation) pairs from a team/about
    page. Crude heuristic by design — this is discovery, not verified
    enrichment. Only pulls what's rendered in plain sight on the page.
    """
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    people = []
    blocks = soup.find_all(["h1", "h2", "h3", "h4", "p", "span", "div"])

    for i, block in enumerate(blocks):
        text = block.get_text(" ", strip=True)
        if not text or len(text) > 120:
            continue
        lowered = text.lower()
        for kw in DESIGNATION_KEYWORDS:
            if kw in lowered:
                name_candidate = None
                if i > 0:
                    prev_text = blocks[i - 1].get_text(" ", strip=True)
                    if prev_text and 1 <= len(prev_text.split()) <= 4:
                        name_candidate = prev_text
                people.append({"name": name_candidate, "designation": _format_designation(kw)})
                break
    return people


def extract_from_website(homepage_url: str) -> dict:
    """
    Full public-data extraction pass: homepage -> contact/about/team
    subpages -> emails, phones, socials, people. Everything returned here
    was visible on a plain public page load, nothing behind a login.
    """
    result = {
        "contact_page": None,
        "about_page": None,
        "team_page": None,
        "emails": [],
        "phones": [],
        "social_links": {},
        "people": [],
    }

    homepage_html = fetch_page(homepage_url)
    if not homepage_html:
        return result

    result["social_links"] = extract_social_links(homepage_html, homepage_url)
    result["emails"].extend(extract_emails(homepage_html))
    result["phones"].extend(extract_phone_numbers(homepage_html))

    subpages = find_subpages(homepage_html, homepage_url)
    result["contact_page"] = subpages.get("contact_page")
    result["about_page"] = subpages.get("about_page")
    result["team_page"] = subpages.get("team_page")

    for page_type in ["contact_page", "about_page", "team_page"]:
        url = result[page_type]
        if not url:
            continue
        html = fetch_page(url)
        result["emails"].extend(extract_emails(html))
        result["phones"].extend(extract_phone_numbers(html))
        if page_type == "team_page":
            result["people"].extend(extract_people(html))

    result["emails"] = sorted(set(result["emails"]))
    result["phones"] = sorted(set(result["phones"]))
    return result


if __name__ == "__main__":
    # quick manual test: python -m extraction.page_extractor
    import json
    print(json.dumps(extract_from_website("https://anthropic.com"), indent=2))
