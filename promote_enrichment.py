#!/usr/bin/env python3
"""
Pillar 2 — Promote Script
After running enrich on rescue_candidates.json, some records may have
gotten a "_enrichment.discovered_website". This copies it into the main
"website" field so verify_leads.py can check it.
"""

import json

INPUT_FILE = "enriched_leads.json"


def main():
    with open(INPUT_FILE, "r", encoding="utf-8") as fh:
        records = json.load(fh)

    promoted_count = 0
    for rec in records:
        enrichment = rec.get("_enrichment", {})
        discovered = enrichment.get("discovered_website")
        if discovered and not rec.get("website"):
            rec["website"] = discovered
            promoted_count += 1
        discovered_emails = enrichment.get("discovered_emails")
        if discovered_emails:
            rec["emails"] = list(set(rec.get("emails", []) + discovered_emails))

    with open("rescue_ready_to_verify.json", "w", encoding="utf-8") as fh:
        json.dump(records, fh, indent=2, ensure_ascii=False)

    print("=" * 40)
    print(f"Records processed: {len(records)}")
    print(f"Websites promoted from enrichment: {promoted_count}")
    print("Output: rescue_ready_to_verify.json")
    print("=" * 40)


if __name__ == "__main__":
    main()