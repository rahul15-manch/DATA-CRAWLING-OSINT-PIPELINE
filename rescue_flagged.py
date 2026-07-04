#!/usr/bin/env python3
"""
Pillar 2 — Rescue Script
Takes flagged_leads.json (output of clean_leads.py), drops the records that
are genuinely NOT companies (directory/article pages), and keeps everything
else so it can be run back through enrich_leads.py / verify_leads.py.

Input:  flagged_leads.json
Output: rescue_candidates.json   -> real companies worth enriching further
        dropped_not_companies.json -> directory/article pages (discarded)
"""

import json

INPUT_FILE = "flagged_leads.json"


def main():
    with open(INPUT_FILE, "r", encoding="utf-8") as fh:
        records = json.load(fh)

    rescue_candidates = []
    dropped = []

    for rec in records:
        flags = rec.get("_flags", [])
        if "directory_or_article_page" in flags:
            dropped.append(rec)
        else:
            rescue_candidates.append(rec)

    with open("rescue_candidates.json", "w", encoding="utf-8") as fh:
        json.dump(rescue_candidates, fh, indent=2, ensure_ascii=False)

    with open("dropped_not_companies.json", "w", encoding="utf-8") as fh:
        json.dump(dropped, fh, indent=2, ensure_ascii=False)

    print("=" * 40)
    print(f"Total flagged records read: {len(records)}")
    print(f"Dropped (directory/article pages): {len(dropped)}")
    print(f"Rescue candidates (real companies, worth enriching): {len(rescue_candidates)}")
    print("=" * 40)
    print("Next: point enrich_leads.py's INPUT_FILE at 'rescue_candidates.json' and run it.")


if __name__ == "__main__":
    main()