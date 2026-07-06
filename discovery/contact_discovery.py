"""
Contact Discovery: given a company, finds a candidate decision-maker.

Scope: finds a plausible person + designation + LinkedIn/page where they
were found. Only includes an email if it's plainly visible in the search
snippet — this module does NOT hunt for, guess, or verify emails.
That enrichment/verification work belongs to Pillar 2.
"""

import re

from query.query_generator import generate_contact_queries
from discovery.search_backend import run_search

EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

DESIGNATION_KEYWORDS = ["founder", "co-founder", "ceo", "cto", "director", "head of"]
ACRONYMS = {"ceo", "cto"}


def _extract_public_email(text: str):
    """Only pulls an email if it's plainly sitting in the text already."""
    if not text:
        return None
    match = EMAIL_PATTERN.search(text)
    return match.group(0) if match else None


def _guess_designation(text: str):
    if not text:
        return None
    lowered = text.lower()
    for kw in DESIGNATION_KEYWORDS:
        if kw in lowered:
            return kw.upper() if kw in ACRONYMS else kw.title()
    return None


def discover_contact(company: str) -> dict:
    """
    Returns a single best-guess contact dict for the given company:
    {contact_name, designation, email, linkedin, source}
    or an empty dict if nothing plausible was found.
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

            # Only treat this as a contact hit if we found a LinkedIn
            # profile or a recognizable designation keyword nearby.
            if is_linkedin or designation:
                return {
                    "contact_name": title.split(" - ")[0].strip() if is_linkedin else None,
                    "designation": designation,
                    "email": _extract_public_email(combined_text),
                    "linkedin": url if is_linkedin else None,
                    "source": "LinkedIn" if is_linkedin else "Company Website",
                }

    return {}


if __name__ == "__main__":
    # quick manual test: python -m discovery.contact_discovery
    print(discover_contact("ABC AI"))
