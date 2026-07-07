#!/usr/bin/env python3
"""
Pillar 2 — Polish Script (final pass)

Fixes remaining issues found on manual review of FINAL_leads_for_pillar4.json:
  1. Duplicate emails/people within the same record
  2. "Mass email list" records — pages where the scraped emails belong to many
     DIFFERENT companies (a directory/blog footer got scraped, not one
     company's real contacts). Detected by: emails spanning many different
     domains that don't match the record's own website domain.
  3. Garbage person names — an email address or a phone number got scraped
     into the "name" field instead of an actual person's name.
  4. Broader article/directory-page detection (multi-word title gaps that
     the earlier regex missed, e.g. "The Real Impact of X on Y").

Input:  FINAL_leads_for_pillar4.json
Output: FINAL_leads_for_pillar4.json  (overwritten, polished)
        polish_dropped.json          (what got cut here, for your review)
"""

import json
import re
from collections import Counter
from urllib.parse import urlparse

INPUT_FILE = "FINAL_leads_for_pillar4.json"

ARTICLE_PATTERNS = [
    r"^list of\b", r"^what is\b", r"^what are\b", r"^how to\b",
    r"^the .{0,40} of\b",           # "The Real Impact of X on Y" (widened gap)
    r"^guide to\b", r"\bguide$",
    r"^top\s+\d*", r"^\d+\s+(top|best|different)",
    r"companies\s+in\b", r"companies\s+to\s+know", r"jobs\s+in\b",
    r"^popular\b", r"^best\b.*\(?\d{4}\)?$",
    r"largest\s+.{0,40}\s+by\b",     # widened gap
    r"^does\b", r"^is\b.*\?$", r"vs\s+human", r"^free\b.*writer",
    r"connects.*to\b", r"overview trends", r"current startups",
    r"^»", r":\s*meaning", r"assistant:.*meaning",
]
WIKI_DOMAINS = ("wikipedia.org", "britannica.com")


def is_article_page(rec: dict) -> bool:
    name = (rec.get("company_name") or "").lower().strip()
    website = (rec.get("website") or "").lower()
    if any(re.search(p, name) for p in ARTICLE_PATTERNS):
        return True
    if any(domain in website for domain in WIKI_DOMAINS):
        return True
    if name in ("artificial intelligence", "ai", "artificial intelligence (ai)"):
        return True
    return False


def get_domain(url_or_email_side: str) -> str:
    if not url_or_email_side:
        return ""
    if "@" in url_or_email_side:
        return url_or_email_side.split("@")[-1].lower()
    try:
        netloc = urlparse(url_or_email_side).netloc or url_or_email_side
        return netloc.replace("www.", "").lower()
    except Exception:
        return ""


def dedupe_list(items):
    seen = set()
    out = []
    for item in items:
        key = item.strip().lower() if isinstance(item, str) else item
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def dedupe_people(people):
    seen = set()
    out = []
    for p in people:
        key = ((p.get("name") or "").strip().lower(), (p.get("designation") or "").strip().lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def looks_like_garbage_name(name: str) -> bool:
    if "@" in name:
        return True
    digit_ratio = sum(c.isdigit() for c in name) / max(len(name), 1)
    if digit_ratio > 0.3:  # mostly digits -> probably a phone number, not a name
        return True
    return False


def fix_emails(rec: dict):
    """Drop the whole email list if it looks like a scraped directory/footer
    (many different domains, none matching the company's own site)."""
    emails = dedupe_list(rec.get("emails", []))
    if not emails:
        rec["emails"] = []
        return

    website_domain = get_domain(rec.get("website", ""))
    email_domains = [get_domain(e) for e in emails]
    domain_counts = Counter(email_domains)

    # If emails span more than 4 distinct domains AND none of them is the
    # company's own website domain, this is very likely an aggregator/footer
    # scrape, not this company's real contacts.
    if len(domain_counts) > 4 and website_domain not in domain_counts:
        rec["emails"] = []
        rec["_mass_email_list_dropped"] = True
        return

    # Otherwise, prefer emails matching the website's own domain if any exist
    if website_domain and website_domain in domain_counts:
        rec["emails"] = [e for e in emails if get_domain(e) == website_domain]
    else:
        rec["emails"] = emails


def fix_people(rec: dict):
    people = dedupe_people(rec.get("people", []))
    cleaned = [p for p in people if not looks_like_garbage_name((p.get("name") or "").strip())]
    rec["people"] = cleaned


def main():
    with open(INPUT_FILE, "r", encoding="utf-8") as fh:
        records = json.load(fh)

    kept, dropped = [], []

    for rec in records:
        if is_article_page(rec):
            dropped.append({**rec, "_drop_reason": "article_or_directory_page"})
            continue

        rec["phones"] = dedupe_list(rec.get("phones", []))
        fix_emails(rec)
        fix_people(rec)

        # After all this cleanup, does the record still have something usable?
        if not rec["emails"] and not rec["phones"] and not rec.get("people"):
            # last resort: keep only if it has a linkedin_company or website that's clearly a real product/company domain
            if not rec.get("linkedin_company"):
                dropped.append({**rec, "_drop_reason": "nothing_usable_after_polish"})
                continue

        kept.append(rec)

    with open("FINAL_leads_for_pillar4.json", "w", encoding="utf-8") as fh:
        json.dump(kept, fh, indent=2, ensure_ascii=False)

    with open("polish_dropped.json", "w", encoding="utf-8") as fh:
        json.dump(dropped, fh, indent=2, ensure_ascii=False)

    print("=" * 40)
    print(f"Records before polish: {len(records)}")
    print(f"Dropped at polish: {len(dropped)}")
    print(f"Final polished records: {len(kept)}")
    print("Output: FINAL_leads_for_pillar4.json (overwritten)")
    print("=" * 40)


if __name__ == "__main__":
    main()