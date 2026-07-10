

import json
import re
import glob
from collections import defaultdict

# ---------- Config ----------

import sys
import pathlib

# --------------- Input / Output wiring ---------------
# Usage:
#   python clean_leads.py                                  (legacy: reads data-*.json)
#   python clean_leads.py input.json                       (reads one file, writes to output/clean/)
#   python clean_leads.py input.json output_clean.json     (explicit output path)

if len(sys.argv) >= 2:
    INPUT_FILES = [sys.argv[1]]
else:
    INPUT_FILES = sorted(glob.glob("data-*.json"))  # legacy fallback

if len(sys.argv) >= 3:
    _OUT_CLEAN   = pathlib.Path(sys.argv[2])
    _OUT_FLAGGED = _OUT_CLEAN.parent / (_OUT_CLEAN.stem + "_flagged" + _OUT_CLEAN.suffix)
    _OUT_REPORT  = _OUT_CLEAN.parent / (_OUT_CLEAN.stem + "_report.txt")
else:
    _stem        = pathlib.Path(INPUT_FILES[0]).stem if INPUT_FILES else "leads"
    _OUT_CLEAN   = pathlib.Path("output") / "clean"    / f"{_stem}.json"
    _OUT_FLAGGED = pathlib.Path("output") / "clean"    / f"{_stem}_flagged.json"
    _OUT_REPORT  = pathlib.Path("output") / "clean"    / f"{_stem}_report.txt"

# Article/directory page indicators in "company_name" (these are not companies)
DIRECTORY_PATTERNS = [
    r"^top\s+\d*", r"^\d+\s+(top|best)", r"top\s+\d+", r"best\s+\d+",
    r"companies\s+in\b", r"companies\s+to\s+know", r"jobs\s+in\b",
    r"^popular\b", r"services\s+in\b.*\(?\d{4}\)?$", r"in\s+\w+\s*\(?\d{4}\)?$",
]

# Obvious junk / placeholder email patterns
JUNK_EMAIL_PATTERNS = [
    r"\.(png|jpg|jpeg|gif|svg|webp)$",   # scraped image filenames
    r"^your@email\.com$",                 # placeholder text
    r"^(test|example|sample|noreply|no-reply)@",
]

# Broken unicode-escape artifact (e.g. "u003e..." leaking from \u003e)
UNICODE_ARTIFACT_RE = re.compile(r"^u00[0-9a-f]{2}", re.IGNORECASE)

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
PHONE_DIGITS_RE = re.compile(r"\d")


def is_directory_page(name: str) -> bool:
    if not name:
        return True
    lname = name.lower()
    return any(re.search(p, lname) for p in DIRECTORY_PATTERNS)


def clean_unicode_artifact(email: str) -> str:
    """Fix leaked \\u003e-style escapes that were scraped in as literal text."""
    if UNICODE_ARTIFACT_RE.match(email):
        # u003e -> '>' , strip stray leading escape remnants entirely for emails
        return UNICODE_ARTIFACT_RE.sub("", email)
    return email


def classify_email(raw_email: str):
    """Return (cleaned_email, status) where status is 'ok' | 'junk' | 'malformed'."""
    email = clean_unicode_artifact(raw_email.strip())

    for pat in JUNK_EMAIL_PATTERNS:
        if re.search(pat, email, re.IGNORECASE):
            return email, "junk"

    if not EMAIL_RE.match(email):
        return email, "malformed"

    return email, "ok"


def verify_mx(domain: str) -> bool:
    """
    Placeholder for live MX-record verification.
    Requires network access (e.g. `dns.resolver.resolve(domain, 'MX')`
    from dnspython, or a 3rd-party email verification API).
    Returns True/False when wired up; currently just documents the hook.
    """
    raise NotImplementedError(
        "No network access in this environment. "
        "Wire this up with dnspython or an email-verification API "
        "when running with connectivity."
    )


def clean_people(people):
    """Drop person entries that are just noise (null name with a designation,
    or a name that's clearly a product/service label)."""
    cleaned = []
    dropped = 0
    PRODUCT_LABEL_HINTS = ("services", "systems", "development", "solutions", "erp", "mvp")
    for p in people or []:
        name = (p.get("name") or "").strip()
        if not name:
            dropped += 1
            continue
        if any(hint in name.lower() for hint in PRODUCT_LABEL_HINTS):
            dropped += 1
            continue
        cleaned.append(p)
    return cleaned, dropped


def process_record(rec, source_file):
    issues = []

    # 1. Directory/article page check
    if is_directory_page(rec.get("company_name")):
        issues.append("directory_or_article_page")

    # 2. Email cleaning/classification
    clean_emails = []
    for raw in rec.get("emails", []) or []:
        cleaned, status = classify_email(raw)
        if status == "ok":
            clean_emails.append(cleaned)
        else:
            issues.append(f"email_{status}:{raw}")
    rec["emails"] = clean_emails

    # 3. Phone sanity check (must contain at least 7 digits)
    clean_phones = []
    for raw in rec.get("phones", []) or []:
        digit_count = len(re.findall(r"\d", raw))
        if digit_count >= 7:
            clean_phones.append(raw)
        else:
            issues.append(f"phone_malformed:{raw}")
    rec["phones"] = clean_phones

    # 4. People cleanup
    rec["people"], dropped_people = clean_people(rec.get("people"))
    if dropped_people:
        issues.append(f"people_dropped:{dropped_people}")

    # 5. Sparse record check (no website AND no email AND no phone)
    if not rec.get("website") and not rec["emails"] and not rec["phones"]:
        issues.append("sparse_no_contact_channel")

    rec["_source_file"] = source_file
    rec["_flags"] = issues
    return rec


def main():
    all_records = []
    for f in INPUT_FILES:
        with open(f, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        for rec in data:
            all_records.append(process_record(rec, f))

    # Dedup by (company_name, website) — keep first occurrence
    seen = set()
    deduped = []
    dup_count = 0
    for rec in all_records:
        key = (rec.get("company_name", "").strip().lower(), (rec.get("website") or "").strip().lower())
        if key in seen:
            dup_count += 1
            continue
        seen.add(key)
        deduped.append(rec)

    clean_records = [r for r in deduped if not r["_flags"]]
    flagged_records = [r for r in deduped if r["_flags"]]

    _OUT_CLEAN.parent.mkdir(parents=True, exist_ok=True)

    with open(_OUT_CLEAN, "w", encoding="utf-8") as fh:
        json.dump(clean_records, fh, indent=2, ensure_ascii=False)

    with open(_OUT_FLAGGED, "w", encoding="utf-8") as fh:
        json.dump(flagged_records, fh, indent=2, ensure_ascii=False)

    # Tally flag reasons
    tally = defaultdict(int)
    for r in flagged_records:
        for issue in r["_flags"]:
            tag = issue.split(":")[0]
            tally[tag] += 1

    with open(_OUT_REPORT, "w", encoding="utf-8") as fh:
        fh.write("PILLAR 2 — LEAD CLEANING REPORT\n")
        fh.write("=" * 40 + "\n")
        fh.write(f"Input files: {', '.join(INPUT_FILES)}\n")
        fh.write(f"Total raw records: {len(all_records)}\n")
        fh.write(f"Duplicates removed: {dup_count}\n")
        fh.write(f"Records after dedup: {len(deduped)}\n\n")
        fh.write(f"CLEAN records (no issues): {len(clean_records)}\n")
        fh.write(f"FLAGGED records (need review/enrichment): {len(flagged_records)}\n\n")
        fh.write("Flag breakdown:\n")
        for tag, count in sorted(tally.items(), key=lambda x: -x[1]):
            fh.write(f"  {tag:30s} {count}\n")
        fh.write("\nNOTE: Live MX-record email verification was NOT run (no network\n")
        fh.write("access in this environment). See verify_mx() in the script for the hook.\n")

    print(open(_OUT_REPORT).read())
    print(f"Output -> {_OUT_CLEAN}")


if __name__ == "__main__":
    main()
