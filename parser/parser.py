"""
Deliberately thin. Discovery only needs to avoid handing off obvious
duplicates — deep validation (email verification, broken-link checks,
phone regex) belongs to Pillar 2 / Pillar 4, not here.
"""


def dedupe_companies(companies: list) -> list:
    """Dedupe by company name (case-insensitive), keeping the first hit."""
    seen = set()
    unique = []
    for c in companies:
        key = (c.get("company") or "").strip().lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


if __name__ == "__main__":
    sample = [
        {"company": "ABC AI"},
        {"company": "abc ai"},
        {"company": "XYZ Labs"},
    ]
    print(dedupe_companies(sample))
