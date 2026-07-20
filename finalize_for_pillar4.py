#!/usr/bin/env python3


import json
import re

import sys
import pathlib


if len(sys.argv) >= 2:
    INPUT_FILES = [sys.argv[1]]
else:
    INPUT_FILES = ["verified_leads_original.json", "verified_leads_rescue.json"]  # legacy

if len(sys.argv) >= 3:
    _OUT_FINAL   = pathlib.Path(sys.argv[2])
    _OUT_DROPPED = _OUT_FINAL.parent / (_OUT_FINAL.stem + "_dropped" + _OUT_FINAL.suffix)
else:
    _stem        = pathlib.Path(INPUT_FILES[0]).stem
    _OUT_FINAL   = pathlib.Path("output") / "final" / f"{_stem}.json"
    _OUT_DROPPED = pathlib.Path("output") / "final" / f"{_stem}_dropped.json"

# Stronger article/definition/directory page patterns — final safety net
ARTICLE_PATTERNS = [
    r"^list of\b", r"^what is\b", r"^what are\b", r"^how to\b", r"^why\b",
    r"^the \w+ of\b", r"^guide to\b", r"\bguide$", r"^top\s+\d*",
    r"^\d+\s+(top|best|different)", r"companies\s+in\b", r"companies\s+to\s+know",
    r"jobs\s+in\b", r"^popular\b", r"^best\b.*\(?\d{4}\)?$", r"largest\s+\w+\s+by\b",
    r"^does\b", r"^is\b.*\?$", r"vs\s+human", r"^free\b.*writer",
]

WIKI_DOMAINS = ("wikipedia.org", "britannica.com")


def is_article_page(rec: dict) -> bool:
    name = (rec.get("company_name") or "").lower().strip()
    website = (rec.get("website") or "").lower()

    if any(re.search(p, name) for p in ARTICLE_PATTERNS):
        return True
    if any(domain in website for domain in WIKI_DOMAINS):
        return True
    # Bare abstract-noun titles with no company signal at all (heuristic:
    # very short generic name AND no linkedin_company AND industry-only match)
    if name in ("artificial intelligence", "ai", "artificial intelligence (ai)"):
        return True
    return False


def clean_people(people):
    """Second pass — catch UI-scrape junk that slipped through the first clean
    (arrows, button text like 'Read bio', 'Learn more', 'Close', etc.)."""
    UI_JUNK = (
        "read bio", "learn more", "close", "explore the topics", "summary",
        "translations available", "cook more", "your privacy choices",
        "board of directors", "cookbooks", "terms of service",
    )
    cleaned = []
    for p in people or []:
        name = (p.get("name") or "").strip()
        if not name:
            continue
        if len(name) <= 2:  # single chars / arrows / symbols
            continue
        if any(junk in name.lower() for junk in UI_JUNK):
            continue
        cleaned.append(p)
    return cleaned


def finalize_record(rec: dict) -> dict:
    enrichment = rec.get("_enrichment", {})
    discovered_emails = enrichment.get("discovered_emails", [])
    rec["emails"] = sorted(list(set(rec.get("_verified_emails", []) + discovered_emails)))
    rec["phones"] = rec.get("_verified_phones", [])
    
    if not rec.get("website") and enrichment.get("discovered_website"):
        rec["website"] = enrichment["discovered_website"]
        
    rec["people"] = clean_people(rec.get("people"))

    # Strip all debug/internal fields
    for field in list(rec.keys()):
        if field.startswith("_"):
            rec.pop(field, None)

    return rec


def main():
    all_records = []
    for f in INPUT_FILES:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            all_records.extend(data)
            print(f"Loaded {len(data)} records from {f}")
        except FileNotFoundError:
            print(f"WARNING: {f} not found, skipping.")

    kept, dropped = [], []

    for rec in all_records:
        if is_article_page(rec):
            dropped.append({**rec, "_drop_reason": "article_or_definition_page"})
            continue

        enrichment = rec.get("_enrichment", {})
        website_reachable = rec.get("_website_reachable") or bool(enrichment.get("discovered_website"))
        has_email = bool(rec.get("_verified_emails")) or bool(enrichment.get("discovered_emails"))
        has_phone = bool(rec.get("_verified_phones"))

        if not (has_email or has_phone or website_reachable):
            dropped.append({**rec, "_drop_reason": "nothing_usable_after_verification"})
            continue

        kept.append(finalize_record(rec))

    # Final dedup
    seen = set()
    final = []
    for rec in kept:
        key = (rec.get("company_name", "").strip().lower(), (rec.get("website") or "").strip().lower())
        if key in seen:
            continue
        seen.add(key)
        final.append(rec)

    _OUT_FINAL.parent.mkdir(parents=True, exist_ok=True)

    with open(_OUT_FINAL, "w", encoding="utf-8") as fh:
        json.dump(final, fh, indent=2, ensure_ascii=False)

    with open(_OUT_DROPPED, "w", encoding="utf-8") as fh:
        json.dump(dropped, fh, indent=2, ensure_ascii=False)

    print("=" * 40)
    print(f"Total records loaded: {len(all_records)}")
    print(f"Dropped at finalize (article pages / nothing usable): {len(dropped)}")
    print(f"Final clean records: {len(final)}")
    print(f"Output -> {_OUT_FINAL}")
    print("=" * 40)


if __name__ == "__main__":
    main()