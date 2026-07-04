#!/usr/bin/env python3
"""
Pillar 2 — Final Merge Script
"""

import json

INPUT_FILES = [
    "verified_leads_original.json",
    "verified_leads_rescue.json",
] 


DEBUG_FIELDS = [
    "_flags", "_source_file", "_verified_emails", "_verified_phones",
    "_website_reachable", "_verification_notes", "_verification_passed",
    "_enrichment",
]


def clean_record(rec: dict) -> dict:
    for field in DEBUG_FIELDS:
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

    cleaned = [clean_record(r) for r in all_records]

    seen = set()
    final = []
    for rec in cleaned:
        key = (rec.get("company_name", "").strip().lower(), (rec.get("website") or "").strip().lower())
        if key in seen:
            continue
        seen.add(key)
        final.append(rec)

    with open("FINAL_leads_for_pillar4.json", "w", encoding="utf-8") as fh:
        json.dump(final, fh, indent=2, ensure_ascii=False)

    print("=" * 40)
    print(f"Total records merged: {len(cleaned)}")
    print(f"After final dedup: {len(final)}")
    print("Output: FINAL_leads_for_pillar4.json")
    print("=" * 40)


if __name__ == "__main__":
    main()