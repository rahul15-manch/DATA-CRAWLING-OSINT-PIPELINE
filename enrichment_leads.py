#!/usr/bin/env python3
"""
Pillar 2 — OSINT Stack Integration
Enrichment Script (Step 3, after verify_leads.py)

Requires internet access. Run this on your own machine, not in a sandbox.

Install dependencies first:
    pip install requests python-whois

What it does for records missing a website/email:
  1. Domain guessing: builds candidate domains from the company name
     (e.g. "Cloud Certitude" -> cloudcertitude.com, cloudcertitude.in, ...)
     and checks which ones actually respond.
  2. WHOIS lookup: for any domain found (guessed or existing), pulls
     registrant org / creation date where the registry exposes it
     (many are privacy-redacted — that's normal, not a bug).
  3. (Optional) Hunter.io-style email-finder hook: if you have an API key
     for a service like Hunter.io, Clearbit, or Apollo, plug it into
     find_emails_via_api() to auto-discover emails for a found domain.
     Left disabled by default since it needs a paid key.

Input:  unverified_leads.json (or flagged_leads.json / cleaned_leads.json —
        point INPUT_FILE at whichever file has the sparse records you want
        to enrich)
Output: enriched_leads.json  -> same records, with any newly discovered
        website/domain/whois info added under "_enrichment"
"""

import json
import re
import requests

try:
    import whois  # python-whois package
except ImportError:
    whois = None

import sys
import pathlib

# --------------- Input / Output wiring ---------------
# Usage:
#   python enrichment_leads.py                          (legacy: reads rescue_candidates.json)
#   python enrichment_leads.py input.json               (writes to output/enriched/)
#   python enrichment_leads.py input.json output.json   (explicit output path)

INPUT_FILE = sys.argv[1] if len(sys.argv) >= 2 else "rescue_candidates.json"

if len(sys.argv) >= 3:
    _OUT_ENRICHED = pathlib.Path(sys.argv[2])
else:
    _stem         = pathlib.Path(INPUT_FILE).stem
    _OUT_ENRICHED = pathlib.Path("output") / "enriched" / f"{_stem}.json"

REQUEST_TIMEOUT = 6
CANDIDATE_TLDS = [".com", ".in", ".co.in", ".io", ".org"]

# ---- Optional: paid API key for an email-finder service ----
# Leave blank to skip. If you have a Hunter.io key, set it here.
HUNTER_API_KEY = ""


def check_domain_mx(domain: str) -> bool:
    """Check if the domain has at least one valid MX record."""
    try:
        import dns.resolver
        answers = dns.resolver.resolve(domain, "MX", lifetime=4)
        return len(answers) > 0
    except Exception:
        return False


def guess_emails_from_domain(domain: str) -> list:
    """Generate common email prefixes for the domain if it has MX records."""
    if not check_domain_mx(domain):
        return []
    
    prefixes = ["info", "hello", "contact", "sales", "support", "admin"]
    return [f"{p}@{domain}" for p in prefixes]


def slugify_company_name(name: str) -> str:
    """Turn 'Cloud Certitude Pvt Ltd' -> 'cloudcertitude'."""
    name = name.lower()
    name = re.sub(r"\b(pvt|ltd|private|limited|inc|llp|technologies|technology|solutions|services|consulting|group)\b", "", name)
    name = re.sub(r"[^a-z0-9]", "", name)
    return name


def guess_domain(company_name: str):
    """Try common TLDs against a slugified company name, return first that responds."""
    slug = slugify_company_name(company_name)
    if not slug:
        return None, []

    tried = []
    for tld in CANDIDATE_TLDS:
        candidate = f"{slug}{tld}"
        tried.append(candidate)
        url = f"https://{candidate}"
        try:
            resp = requests.get(
                url,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; LeadEnricher/1.0)"},
            )
            if resp.status_code < 400:
                return candidate, tried
        except requests.exceptions.RequestException:
            continue
    return None, tried


def whois_lookup(domain: str) -> dict:
    """Pull whatever WHOIS exposes (often privacy-redacted for orgs — that's expected)."""
    if whois is None:
        return {"error": "python-whois not installed"}
    try:
        w = whois.whois(domain)
        return {
            "registrar": w.registrar,
            "creation_date": str(w.creation_date) if w.creation_date else None,
            "org": getattr(w, "org", None),
            "country": getattr(w, "country", None),
        }
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def find_emails_via_api(domain: str) -> list:
    """
    Optional hook for a paid email-finder API (Hunter.io shown as example).
    Returns [] if no API key is configured.
    """
    if not HUNTER_API_KEY:
        return []
    try:
        resp = requests.get(
            "https://api.hunter.io/v2/domain-search",
            params={"domain": domain, "api_key": HUNTER_API_KEY},
            timeout=REQUEST_TIMEOUT,
        )
        data = resp.json()
        emails = [e["value"] for e in data.get("data", {}).get("emails", [])]
        return emails
    except Exception:
        return []


def enrich_record(rec: dict) -> dict:
    enrichment = {}

    domain = None
    if rec.get("website"):
        domain = re.sub(r"^https?://(www\.)?", "", rec["website"]).split("/")[0]
        enrichment["domain_source"] = "existing_website"
    else:
        guessed, tried = guess_domain(rec.get("company_name", ""))
        enrichment["domains_tried"] = tried
        if guessed:
            domain = guessed
            enrichment["domain_source"] = "guessed_and_verified"
            enrichment["discovered_website"] = f"https://{guessed}"

    if domain:
        enrichment["whois"] = whois_lookup(domain)
        api_emails = find_emails_via_api(domain)
        if api_emails:
            enrichment["discovered_emails"] = api_emails
        else:
            guessed_emails = guess_emails_from_domain(domain)
            if guessed_emails:
                enrichment["discovered_emails"] = guessed_emails

    rec["_enrichment"] = enrichment
    return rec


def main():
    with open(INPUT_FILE, "r", encoding="utf-8") as fh:
        records = json.load(fh)

    print(f"Enriching {len(records)} records from {INPUT_FILE} (live web/WHOIS calls, may take a while)...")

    enriched = []
    for i, rec in enumerate(records, 1):
        enriched.append(enrich_record(rec))
        if i % 10 == 0 or i == len(records):
            print(f"  processed {i}/{len(records)}")

    _OUT_ENRICHED.parent.mkdir(parents=True, exist_ok=True)

    with open(_OUT_ENRICHED, "w", encoding="utf-8") as fh:
        json.dump(enriched, fh, indent=2, ensure_ascii=False)

    found_new_domain = sum(1 for r in enriched if r["_enrichment"].get("domain_source") == "guessed_and_verified")
    print("\n" + "=" * 40)
    print(f"Records processed: {len(enriched)}")
    print(f"New domains discovered via guessing: {found_new_domain}")
    print(f"Output -> {_OUT_ENRICHED}")
    print("=" * 40)


if __name__ == "__main__":
    main()