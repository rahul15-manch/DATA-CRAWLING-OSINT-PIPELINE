#!/usr/bin/env python3


import json
import re
import time

import requests
from bs4 import BeautifulSoup

INPUT_FILE = "registry_matched_leads.json"
OUTPUT_FILE = "socially_enriched_leads.json"
REQUEST_TIMEOUT = 6
REQUEST_DELAY = 0.5

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; LeadSocialDiscovery/1.0)"}

SOCIAL_DOMAIN_PATTERNS = {
    "linkedin": re.compile(r"linkedin\.com/(company|in|school)/[A-Za-z0-9\-_.%]+", re.I),
    "twitter_x": re.compile(r"(?:twitter\.com|x\.com)/[A-Za-z0-9_]+", re.I),
    "facebook": re.compile(r"facebook\.com/[A-Za-z0-9.\-]+", re.I),
    "instagram": re.compile(r"instagram\.com/[A-Za-z0-9_.]+", re.I),
    "youtube": re.compile(r"youtube\.com/(channel|c|@)[A-Za-z0-9_\-]+", re.I),
}

# Generic paths that are LinkedIn/Twitter/etc UI chrome, not real company profiles
LINK_JUNK = {
    "linkedin.com/company/linkedin",
    "twitter.com/intent",
    "x.com/intent",
    "facebook.com/sharer",
    "facebook.com/plugins",
}


def slugify_company_name(name: str) -> str:
    name = name.lower()
    name = re.sub(r"\b(pvt|ltd|private|limited|inc|llp|technologies|technology|solutions|services|consulting|group)\b", "", name)
    name = re.sub(r"[^a-z0-9]+", "-", name).strip("-")
    return name


def fetch_page_text(url: str) -> str | None:
    if not url:
        return None
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers=HEADERS, allow_redirects=True)
        if resp.status_code < 400:
            return resp.text
    except requests.exceptions.RequestException:
        pass
    return None


def extract_social_links(html: str) -> dict:
    found = {}
    if not html:
        return found

    soup = BeautifulSoup(html, "html.parser")
    hrefs = [a.get("href", "") for a in soup.find_all("a", href=True)]
    haystacks = hrefs + [html]

    for platform, pattern in SOCIAL_DOMAIN_PATTERNS.items():
        for text in haystacks:
            match = pattern.search(text)
            if match:
                url = match.group(0)
                if any(junk in url for junk in LINK_JUNK):
                    continue
                found[platform] = "https://" + url.split("://")[-1]
                break
    return found


def guess_linkedin_company(company_name: str) -> dict:
    """Best-effort slug guess only — NOT verified. See module docstring for why."""
    slug = slugify_company_name(company_name)
    if not slug:
        return {}
    return {
        "url": f"https://www.linkedin.com/company/{slug}",
        "source": "slug_guess",
        "confirmed": False,
        "note": "unverified guess — LinkedIn returns HTTP 200 for both real and fake company URLs, so this cannot be auto-confirmed. Open the link manually to check.",
    }


def discover_social(rec: dict) -> dict:
    social = {}
    pages_to_scan = [
        rec.get("website"),
        rec.get("contact_page"),
        rec.get("about_page"),
        rec.get("team_page"),
    ]

    for page_url in pages_to_scan:
        html = fetch_page_text(page_url)
        links = extract_social_links(html)
        for platform, url in links.items():
            social.setdefault(platform, {"url": url, "source": "found_on_site"})
        if len(social) == len(SOCIAL_DOMAIN_PATTERNS):
            break

    if "linkedin" not in social and rec.get("company_name"):
        guess = guess_linkedin_company(rec["company_name"])
        if guess:
            social["linkedin"] = guess

    return social


def enrich_record(rec: dict) -> dict:
    rec["_social"] = discover_social(rec)
    return rec


def main():
    with open(INPUT_FILE, "r", encoding="utf-8") as fh:
        records = json.load(fh)

    print(f"Discovering social profiles for {len(records)} records (live web calls, may take a while)...")

    enriched = []
    for i, rec in enumerate(records, 1):
        enriched.append(enrich_record(rec))
        if i % 10 == 0 or i == len(records):
            print(f"  processed {i}/{len(records)}")
        time.sleep(REQUEST_DELAY)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as fh:
        json.dump(enriched, fh, indent=2, ensure_ascii=False)

    found_on_site = sum(1 for r in enriched if r["_social"].get("linkedin", {}).get("source") == "found_on_site")
    guessed = sum(1 for r in enriched if r["_social"].get("linkedin", {}).get("source") == "slug_guess")
    with_any = sum(1 for r in enriched if r["_social"])
    print("\n" + "=" * 40)
    print(f"Records processed: {len(enriched)}")
    print(f"Records with at least one social link: {with_any}")
    print(f"LinkedIn actually found on company's own site (trustworthy): {found_on_site}")
    print(f"LinkedIn guessed from name only (unverified, manual review needed): {guessed}")
    print(f"Output written to {OUTPUT_FILE}")
    print("=" * 40)


if __name__ == "__main__":
    main()
