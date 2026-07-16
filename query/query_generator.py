"""
query/query_generator.py
=========================
Generates search/dork queries for a given industry + location.

Design
------
- Queries are built dynamically from dimensions (intent, company type, source)
  rather than hard-coded templates. This produces more varied coverage.
- Deduplication is built-in: no identical queries are returned.
- Backward-compatible: `generate_company_queries(industry, location)` still works.

Supports two lead types:
- "b2b": targets professional/company sources (LinkedIn, company sites)
- "b2c": targets consumer-facing/local sources (directories, review sites)

Supports three intents (optional):
- "discovery": broad queries to surface company names
- "contact": queries to find decision-makers at a company
- "validation": exact company site/about queries
"""
from __future__ import annotations

from query.expansion import build_semantic_company_variants, rank_query_candidate

# ── Company type modifiers ─────────────────────────────────────────────────────
_B2B_COMPANY_TYPES = [
    "company", "companies", "startup", "startups",
    "agency", "agencies", "firm", "firms", "services",
]

_B2B_SOURCES = [
    "site:linkedin.com/company",
    "site:justdial.com",
    "site:indiamart.com",
]

_B2B_MODIFIERS = [
    "-jobs -career -hiring",
    "",
]

_B2C_SOURCES = [
    "site:justdial.com",
    "site:yellowpages.com",
    "site:sulekha.com",
]

# ── Contact query templates (for known company) ───────────────────────────────
_CONTACT_TEMPLATES = [
    'site:linkedin.com/in "{company}" founder OR CEO OR director',
    'site:linkedin.com/in "{company}" "co-founder"',
    '"{company}" "our team" OR "meet the team" OR "leadership"',
    '"{company}" "about us" founder CEO',
    '"{company}" contact email phone',
    '"{company}" site:linkedin.com',
]


def generate_company_queries(
    industry: str,
    location: str,
    lead_type: str = "b2b",
    intent: str = "discovery",
    max_queries: int = 20,
) -> list[str]:
    """
    Generate search queries for discovering companies in an industry + location.

    Parameters
    ----------
    industry  : Target industry (e.g. "Software Companies", "Bakery")
    location  : Target location (e.g. "Noida", "Mumbai")
    lead_type : "b2b" (LinkedIn/professional) or "b2c" (local directories)
    intent    : "discovery" (default), "contact", or "validation"
    max_queries: Maximum number of unique queries to return

    Returns
    -------
    A deduplicated list of search query strings.
    """
    industry = (industry or "").strip().strip('\'"')
    location = (location or "").strip().strip('\'"')
    lead_type = (lead_type or "b2b").lower().strip()
    queries: list[str] = []
    seen: set[str] = set()
    ranked: list[tuple[float, int, str]] = []
    order = 0

    def add(q: str) -> None:
        nonlocal order
        q = q.strip()
        if q and q not in seen:
            seen.add(q)
            ranked.append((rank_query_candidate(q), order, q))
            order += 1

    semantic_variants = build_semantic_company_variants(industry)

    if lead_type == "b2c":
        # Consumer discovery: local directory dorks
        for variant in semantic_variants:
            add(f"{variant} near {location}")
            add(f"{variant} {location} contact")
            add(f"{variant} {location} phone number")
            add(f'"{variant}" "{location}"')
            for source in _B2C_SOURCES:
                add(f"{source} {variant} {location}")
    else:
        # B2B professional discovery

        # 1. Semantic variants first, without source restrictions
        for variant in semantic_variants:
            add(f"{variant} {location}")
            add(f'"{variant}" "{location}"')
            add(f"top {variant} in {location}")
            add(f"{variant} {location} website")
            add(f"{variant} {location} pvt ltd")

        # 2. Source-specific dorks after the semantic layer
        for source in _B2B_SOURCES:
            for variant in semantic_variants:
                add(f"{source} {variant} {location}")
                add(f'{source} "{location}" {variant}')

        # 3. Negative modifier (suppress job listings)
        for variant in semantic_variants:
            add(f'{variant} {location} -jobs -career -hiring')
            add(f'{variant} {location} -job -hiring')

    for _, _, query in sorted(ranked, key=lambda item: (-item[0], item[1])):
        queries.append(query)
        if len(queries) >= max_queries:
            break

    return queries[:max_queries]


def generate_contact_queries(
    company: str,
    has_website: bool = False,
    has_leadership: bool = False,
    has_contact: bool = False,
) -> list[str]:
    """
    Generate queries to find decision-makers at a specific company.

    Parameters
    ----------
    company       : Company name
    has_website   : If True, skip generic website queries (already known)
    has_leadership: If True, skip LinkedIn leadership lookup (already known)
    has_contact   : If True, skip all contact queries (email/phone already known)

    Returns a shorter list when information is already available,
    saving Google request budget.
    """
    if has_contact:
        # Already have everything — no contact queries needed
        return []

    queries: list[str] = []
    seen: set[str] = set()

    def add(q: str) -> None:
        q = q.strip()
        if q and q not in seen:
            seen.add(q)
            queries.append(q)

    if not has_leadership:
        add(f'site:linkedin.com/in "{company}" founder OR CEO OR director')
        add(f'site:linkedin.com/in "{company}" "co-founder"')
        add(f'"{company}" site:linkedin.com')

    add(f'"{company}" "our team" OR "meet the team" OR "leadership"')
    add(f'"{company}" "about us" founder CEO')

    if not has_website:
        add(f'"{company}" contact email phone')

    return queries


if __name__ == "__main__":
    # quick manual test: python query/query_generator.py
    print("B2B company queries (discovery):")
    for q in generate_company_queries("Software Companies", "Noida", lead_type="b2b"):
        print(" ", q)

    print("\nB2C company queries (discovery):")
    for q in generate_company_queries("Bakery", "Mumbai", lead_type="b2c"):
        print(" ", q)

    print("\nContact queries (full):")
    for q in generate_contact_queries("ABC AI"):
        print(" ", q)

    print("\nContact queries (has_leadership=True):")
    for q in generate_contact_queries("ABC AI", has_leadership=True):
        print(" ", q)

    print("\nContact queries (has_contact=True):")
    for q in generate_contact_queries("ABC AI", has_contact=True):
        print(" ", q)
