
import json
import re
import socket

import dns.resolver
import phonenumbers
import requests

import sys
import pathlib

# --------------- Input / Output wiring ---------------
# Usage:
#   python verify_leads.py                              (legacy: reads rescue_ready_to_verify.json)
#   python verify_leads.py input.json                  (writes to output/verified/)
#   python verify_leads.py input.json output.json      (explicit output path)

INPUT_FILE = sys.argv[1] if len(sys.argv) >= 2 else "rescue_ready_to_verify.json"

if len(sys.argv) >= 3:
    _OUT_VERIFIED   = pathlib.Path(sys.argv[2])
    _OUT_UNVERIFIED = _OUT_VERIFIED.parent / (_OUT_VERIFIED.stem + "_unverified" + _OUT_VERIFIED.suffix)
else:
    _stem           = pathlib.Path(INPUT_FILE).stem
    _OUT_VERIFIED   = pathlib.Path("output") / "verified" / f"{_stem}.json"
    _OUT_UNVERIFIED = pathlib.Path("output") / "verified" / f"{_stem}_unverified.json"

DEFAULT_REGION = "IN"  # used when a phone number has no country code prefix
REQUEST_TIMEOUT = 6    # seconds, keep short so a bad site doesn't stall the run

_mx_cache = {}  # avoid re-querying the same domain repeatedly


def verify_email_domain(email: str) -> tuple[bool, str]:
    """Check the email's domain has at least one MX record."""
    try:
        domain = email.split("@", 1)[1]
    except IndexError:
        return False, "no_domain_in_email"

    if domain in _mx_cache:
        return _mx_cache[domain]

    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=5)
        result = (len(answers) > 0, "ok" if len(answers) > 0 else "no_mx_records")
    except dns.resolver.NXDOMAIN:
        result = (False, "domain_does_not_exist")
    except dns.resolver.NoAnswer:
        result = (False, "no_mx_records")
    except (dns.resolver.Timeout, socket.gaierror, Exception) as e:
        result = (False, f"dns_lookup_failed:{type(e).__name__}")

    _mx_cache[domain] = result
    return result


def verify_phone(raw_phone: str) -> tuple[bool, str]:
    """Validate a phone number using Google's libphonenumber rules."""
    try:
        parsed = phonenumbers.parse(raw_phone, DEFAULT_REGION)
    except phonenumbers.NumberParseException as e:
        return False, f"parse_error:{e.error_type}"

    if not phonenumbers.is_possible_number(parsed):
        return False, "not_possible_length"
    if not phonenumbers.is_valid_number(parsed):
        return False, "not_valid_number"
    return True, "ok"


def verify_website(url: str) -> tuple[bool, str]:
    """Check the site actually responds (not dead, not parked-domain redirect)."""
    if not url:
        return False, "no_url"
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        resp = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; LeadVerifier/1.0)"},
        )
        if resp.status_code >= 400:
            return False, f"http_{resp.status_code}"
        return True, "ok"
    except requests.exceptions.SSLError:
        return False, "ssl_error"
    except requests.exceptions.ConnectionError:
        return False, "connection_failed"
    except requests.exceptions.Timeout:
        return False, "timeout"
    except Exception as e:
        return False, f"error:{type(e).__name__}"


def verify_record(rec: dict) -> dict:
    notes = {}

    # Emails
    email_results = {}
    still_valid_emails = []
    for email in rec.get("emails", []):
        ok, reason = verify_email_domain(email)
        email_results[email] = reason
        if ok:
            still_valid_emails.append(email)
    if email_results:
        notes["emails"] = email_results

    # Phones
    phone_results = {}
    still_valid_phones = []
    for phone in rec.get("phones", []):
        ok, reason = verify_phone(phone)
        phone_results[phone] = reason
        if ok:
            still_valid_phones.append(phone)
    if phone_results:
        notes["phones"] = phone_results

    # Website
    website = rec.get("website")
    if website:
        ok, reason = verify_website(website)
        notes["website"] = reason
        website_ok = ok
    else:
        website_ok = None  # no website to check

    rec["_verified_emails"] = still_valid_emails
    rec["_verified_phones"] = still_valid_phones
    rec["_website_reachable"] = website_ok
    rec["_verification_notes"] = notes

    # Passes overall if at least one working contact channel remains
    rec["_verification_passed"] = bool(
        still_valid_emails or still_valid_phones or website_ok
    )
    return rec


def main():
    with open(INPUT_FILE, "r", encoding="utf-8") as fh:
        records = json.load(fh)

    print(f"Verifying {len(records)} records (this makes live DNS/HTTP calls, may take a bit)...")

    verified, unverified = [], []
    for i, rec in enumerate(records, 1):
        rec = verify_record(rec)
        (verified if rec["_verification_passed"] else unverified).append(rec)
        if i % 10 == 0 or i == len(records):
            print(f"  processed {i}/{len(records)}")

    _OUT_VERIFIED.parent.mkdir(parents=True, exist_ok=True)

    with open(_OUT_VERIFIED, "w", encoding="utf-8") as fh:
        json.dump(verified, fh, indent=2, ensure_ascii=False)

    with open(_OUT_UNVERIFIED, "w", encoding="utf-8") as fh:
        json.dump(unverified, fh, indent=2, ensure_ascii=False)

    print("\n" + "=" * 40)
    print(f"Verified (at least 1 working channel): {len(verified)}")
    print(f"Unverified (nothing checked out):      {len(unverified)}")
    print(f"Output -> {_OUT_VERIFIED}")
    print("=" * 40)


if __name__ == "__main__":
    main()
