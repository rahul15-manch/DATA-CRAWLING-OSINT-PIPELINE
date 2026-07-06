"""
Generates search/dork queries for a given industry + location.
This is discovery-scoped: the goal is finding companies and their people,
not enriching or verifying anything about them.

Supports two lead types:
- "b2b": targets professional/company sources (LinkedIn, company sites)
- "b2c": targets consumer-facing/local sources (directories, review sites)
"""

B2B_COMPANY_TEMPLATES = [
    '{industry} {location}',
    'site:linkedin.com/company {industry} {location}',
    '{industry} startup {location}',
    '{industry} services {location}',
]

B2C_COMPANY_TEMPLATES = [
    '{industry} near {location}',
    '{industry} {location} contact',
    'site:justdial.com {industry} {location}',
    'site:yellowpages.com {industry} {location}',
]

CONTACT_QUERY_TEMPLATES = [
    'site:linkedin.com/in "{company}" founder OR CEO OR "co-founder"',
    '"{company}" "our team" OR "about us"',
    '"{company}" contact founder',
]


def generate_company_queries(industry: str, location: str, lead_type: str = "b2b") -> list:
    """
    Returns search queries designed to surface companies/businesses in a
    given industry + location. lead_type picks which source mix to use:
    "b2b" leans on LinkedIn/professional sources, "b2c" leans on local
    directories and consumer-facing listings.
    """
    lead_type = (lead_type or "b2b").lower()
    templates = B2C_COMPANY_TEMPLATES if lead_type == "b2c" else B2B_COMPANY_TEMPLATES
    return [t.format(industry=industry, location=location) for t in templates]


def generate_contact_queries(company: str) -> list:
    """
    Returns search queries designed to surface decision-makers at a
    specific company, once that company has been discovered.
    """
    return [t.format(company=company) for t in CONTACT_QUERY_TEMPLATES]


if __name__ == "__main__":
    # quick manual test: python query/query_generator.py
    print("B2B company queries:")
    for q in generate_company_queries("Software Companies", "Noida", lead_type="b2b"):
        print(" ", q)

    print("\nB2C company queries:")
    for q in generate_company_queries("Bakery", "Mumbai", lead_type="b2c"):
        print(" ", q)

    print("\nContact queries:")
    for q in generate_contact_queries("ABC AI"):
        print(" ", q)
