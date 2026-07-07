"""
discovery/contact_discovery.py
================================
Contact Discovery: given a company, finds a candidate decision-maker.

Scope: finds a plausible person + designation + LinkedIn/page where they
were found. Only includes an email if it's plainly visible in the search
snippet — this module does NOT hunt for, guess, or verify emails.
That enrichment/verification work belongs to Pillar 2.

Task 12: DESIGNATION_KEYWORDS and DESIGNATION_ACRONYMS are now imported
from utils.constants (no local duplication).
"""

import re

from query.query_generator import generate_contact_queries
from discovery.search_backend import run_search
from utils.constants import DESIGNATION_KEYWORDS, DESIGNATION_ACRONYMS
from utils.validators import is_valid_person_name

EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


def _extract_public_email(text: str):
    """Only pulls an email if it's plainly sitting in the text already."""
    if not text:
        return None
    match = EMAIL_PATTERN.search(text)
    return match.group(0) if match else None


def _guess_designation(text: str):
    """Return a formatted designation string if any keyword is found in text."""
    if not text:
        return None
    lowered = text.lower()
    for kw in DESIGNATION_KEYWORDS:
        if kw in lowered:
            return kw.upper() if kw in DESIGNATION_ACRONYMS else kw.title()
    return None


def _extract_name_from_linkedin_title(title: str) -> str:
    """
    LinkedIn profile titles are typically  "Name - Designation at Company".
    Return the part before the first  " - "  separator.
    """
    if not title:
        return ""
    parts = title.split(" - ")
    return parts[0].strip() if parts else ""


def discover_contact(company: str) -> dict:
    """
    Returns a single best-guess contact dict for the given company:
    {contact_name, designation, email, linkedin, source}
    or an empty dict if nothing plausible was found.

    Task 8: Only returns a contact when both a valid person name and a
    designation are present. Bare designations without a realistic name
    are silently skipped.
    """
    queries = generate_contact_queries(company)

    for q in queries:
        print(f"[contact_discovery] running query: {q}")
        raw_results = run_search(q, max_results=5)
        print(f"[contact_discovery]   -> {len(raw_results)} raw results")

        for r in raw_results:
            url = r.get("url") or ""
            title = r.get("title") or ""
            snippet = r.get("snippet") or ""
            combined_text = f"{title} {snippet}"

            is_linkedin = "linkedin.com/in" in url
            designation = _guess_designation(combined_text)

            # Require either a LinkedIn profile URL or a clear designation
            if not (is_linkedin or designation):
                continue

            # Extract and validate the contact name
            if is_linkedin:
                contact_name = _extract_name_from_linkedin_title(title)
            else:
                contact_name = None

            # Task 8: Skip this result if the name is not a realistic person name
            if not is_valid_person_name(contact_name or ""):
                contact_name = None
                if not designation:
                    continue

            return {
                "contact_name": contact_name,
                "designation": designation,
                "email": _extract_public_email(combined_text),
                "linkedin": url if is_linkedin else None,
                "source": "LinkedIn" if is_linkedin else "Company Website",
            }

    return {}


if __name__ == "__main__":
    # quick manual test: python -m discovery.contact_discovery
    print(discover_contact("ABC AI"))
