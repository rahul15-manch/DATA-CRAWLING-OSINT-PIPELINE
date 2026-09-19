"""
scripts/audit_extraction_fields.py
====================================
Phase 1 Step 3 — Extraction field audit.

Run from the project root:
    python scripts/audit_extraction_fields.py

Produces a report showing:
  - Which fields are NULL/empty in the current leads.db
  - What extract_from_website() returns live for each website
  - Whether build_lead_card would preserve the field into the final card
"""

import json
import os
import sqlite3
import sys

# ── Add project root to path ─────────────────────────────────────────────────
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PILLAR1 = os.path.join(ROOT, "pillar1")
for p in (ROOT, PILLAR1):
    if p not in sys.path:
        sys.path.insert(0, p)

DB_PATH = os.path.join(ROOT, "leads.db")

# Fields that should be populated for a usable lead
IMPORTANT_FIELDS = [
    "description", "employees", "founded", "country",
    "location", "tech_stack", "people", "phones",
    "emails", "linkedin", "industry",
]

# Extractor fields (as returned by extract_from_website)
EXTRACTOR_FIELDS = [
    "description", "employees", "founded", "country",
    "location", "tech_stack", "people", "phones",
    "social_links", "contact_page", "about_page", "team_page",
    "industry_detected", "company_type",
]


def audit_db():
    """Audit current leads.db for empty/null fields."""
    print("\n" + "=" * 70)
    print("STEP 1 -- DB FIELD AUDIT (leads table)")
    print("=" * 70)

    if not os.path.exists(DB_PATH):
        print(f"  DB not found at {DB_PATH}")
        return []

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM leads").fetchall()
    conn.close()

    if not rows:
        print("  leads table is empty -- run a pipeline search first.")
        return []

    print(f"  Rows in leads table: {len(rows)}\n")

    totals = {f: 0 for f in IMPORTANT_FIELDS}
    websites = []

    for row in rows:
        r = dict(row)
        print(f"  Company: {r.get('company_name', 'N/A')} | website: {r.get('website', '')}")
        for field in IMPORTANT_FIELDS:
            val = r.get(field)
            # JSON array fields
            if field in ("tech_stack", "people", "emails", "phones"):
                try:
                    parsed = json.loads(val) if val else []
                    populated = bool(parsed)
                except Exception:
                    populated = False
            else:
                populated = bool(val and str(val).strip())

            status = "[OK]" if populated else "[--]"
            print(f"    {status} {field:20s} = {str(val)[:60] if val else 'NULL'}")
            if populated:
                totals[field] += 1

        print()
        if r.get("website"):
            websites.append(r["website"])

    print("\n  SUMMARY -- populated in DB ({}/{}):".format(len(rows), len(rows)))
    for field in IMPORTANT_FIELDS:
        pct = int(100 * totals[field] / len(rows))
        bar = "#" * (pct // 10) + "." * (10 - pct // 10)
        print(f"    {field:20s} [{bar}] {pct:3d}%  ({totals[field]}/{len(rows)})")

    return websites


def audit_extractor(website: str):
    """Call extract_from_website directly and show what it returns."""
    print(f"\n  -> extract_from_website('{website}')")
    try:
        from extraction.page_extractor import extract_from_website
        result = extract_from_website(website)
    except Exception as e:
        print(f"    ERROR: {e}")
        return

    print(f"    Keys returned: {sorted(result.keys())}")
    for field in EXTRACTOR_FIELDS:
        val = result.get(field)
        if field in ("tech_stack", "people", "phones"):
            try:
                parsed = json.loads(val) if isinstance(val, str) else val
                populated = bool(parsed)
                display = str(parsed)[:80] if parsed else "[]"
            except Exception:
                populated = False
                display = str(val)[:80]
        else:
            populated = bool(val and str(val).strip())
            display = str(val)[:80] if val else "None"

        status = "[OK]" if populated else "[--]"
        print(f"    {status} {field:20s} = {display}")


def audit_card_dict():
    """Verify that build_lead_card's card dict includes all extractor fields."""
    print("\n" + "=" * 70)
    print("STEP 3 -- CARD DICT FIELD CHECK (build_lead_card return value)")
    print("=" * 70)
    # These are the keys set in the card dict in main.py L399-426
    CARD_KEYS = [
        "company_name", "website", "linkedin", "industry", "location",
        "contact_page", "about_page", "team_page", "emails", "phones",
        "social_links", "people", "source", "confidence_score", "lead_quality",
        "company_type", "tech_stack", "description", "employees",
        "founded", "country", "relevance_score", "relevance_tier", "relevance_info",
    ]
    print("  Card dict keys in build_lead_card (main.py L399-426):")
    for k in CARD_KEYS:
        print(f"    [OK] {k}")

    print("\n  Cross-check: do all extractor fields make it into the card?")
    missing = []
    for f in EXTRACTOR_FIELDS:
        # Mapping from extractor key -> card key
        mapped = {
            "industry_detected": "industry",
        }.get(f, f)
        if mapped in CARD_KEYS:
            print(f"    [OK] extractor['{f}'] -> card['{mapped}']")
        else:
            print(f"    [!!] extractor['{f}'] -> NOT in card dict!")
            missing.append(f)

    if missing:
        print(f"\n  WARNING: FIELDS LOST BETWEEN EXTRACTOR AND CARD: {missing}")
    else:
        print("\n  All extractor fields are mapped into the card dict.")


if __name__ == "__main__":
    print("\nPHASE 1 -- EXTRACTION FIELD AUDIT")
    print("=" * 70)

    websites = audit_db()

    print("\n" + "=" * 70)
    print("STEP 2 -- LIVE EXTRACTOR OUTPUT (first 2 websites from DB)")
    print("=" * 70)

    for url in websites[:2]:
        audit_extractor(url)

    audit_card_dict()

    print("\n" + "=" * 70)
    print("AUDIT COMPLETE")
    print("=" * 70)
    print("\nInterpret results:")
    print("  If DB has [--] BUT extractor has [OK] -> field is lost in build_lead_card or _save_leads_to_db")
    print("  If extractor has [--] -> fix page_extractor.py patterns for that field")
    print("  If card dict check shows [!!] -> field not passed from extractor to card dict")
