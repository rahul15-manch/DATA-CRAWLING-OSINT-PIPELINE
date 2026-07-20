"""
utils/normalizer.py
====================
Company name normalization and fuzzy deduplication (Task 11).

Goal: merge variants of the same company into a single canonical record.

Examples
--------
IBM / IBM India / IBM Corporation  →  IBM
TCS / Tata Consultancy Services    →  TCS   (via DOMAIN_NAME_OVERRIDES)
Automation Anywhere Inc.           →  Automation Anywhere
"""

import re

from utils.constants import (
    COMPANY_GEOGRAPHIC_QUALIFIERS,
    COMPANY_LEGAL_SUFFIXES,
    DOMAIN_NAME_OVERRIDES,
)
from utils.source_ranker import best_company_record


# ── Internal helpers ──────────────────────────────────────────────────────────

_PUNCTUATION = re.compile(r"[^\w\s\-]")


def _strip_suffixes(words: list[str]) -> list[str]:
    """Remove legal suffixes from the tail of a word list."""
    while words and words[-1].lower().rstrip(".") in COMPANY_LEGAL_SUFFIXES:
        words = words[:-1]
    return words


def _strip_qualifiers(words: list[str]) -> list[str]:
    """Remove geographic qualifiers from the tail of a word list."""
    while words and words[-1].lower() in COMPANY_GEOGRAPHIC_QUALIFIERS:
        words = words[:-1]
    return words


def canonical_company_name(name: str) -> str:
    """
    Return the canonical form of a company name.

    Steps
    -----
    1. Check DOMAIN_NAME_OVERRIDES for exact lower-case match
       (tata consultancy services → TCS is handled upstream; here
        we only handle minor spelling variants of known brands).
    2. Remove surrounding punctuation and normalize whitespace.
    3. Strip trailing legal suffixes (Inc., Ltd., Corp., etc.).
    4. Strip trailing geographic qualifiers (India, International, etc.).
    5. Title-case the result.
    """
    name = (name or "").strip()
    if not name:
        return name

    # Remove non-word characters except hyphen
    name = _PUNCTUATION.sub("", name).strip()
    name = re.sub(r"\s+", " ", name)

    words = name.split()
    words = _strip_suffixes(words)
    words = _strip_qualifiers(words)
    words = _strip_suffixes(words)  # second pass catches "Pvt. Ltd."

    result = " ".join(words)

    # Check against domain overrides (case-insensitive)
    lower_result = result.lower()
    for token, override in DOMAIN_NAME_OVERRIDES.items():
        if lower_result == token or lower_result == override.lower():
            return override

    return result if result else name


def normalization_key(name: str) -> str:
    """
    Generate a stable, case-insensitive lookup key for deduplication.

    This is intentionally lossy — it strips all non-alphanumeric characters
    and lower-cases so that:
        "IBM"
        "IBM India"
        "IBM Corporation"
    all collapse to the same key as long as the canonical form of their
    first two tokens matches.
    """
    canonical = canonical_company_name(name)
    # Keep only alphanumerics, lower-case
    return re.sub(r"[^a-z0-9]", "", canonical.lower())


def normalize_companies(companies: list[dict]) -> list[dict]:
    """
    Deduplicate a list of company records by normalised name.

    When two records share the same normalization_key():
    - The record from the higher-confidence source is kept (via best_company_record)
    - Missing website / LinkedIn from the loser is merged into the winner

    The canonical company name is applied to the final record.

    Returns a new list; input is not mutated.
    """
    by_key: dict[str, dict] = {}

    for company in companies:
        raw_name = company.get("company") or ""
        key = normalization_key(raw_name)
        if not key:
            continue

        if key not in by_key:
            by_key[key] = dict(company)
        else:
            merged = best_company_record(by_key[key], company)
            by_key[key] = merged

    # Apply canonical names to the surviving records
    result = []
    for company in by_key.values():
        company = dict(company)
        company["company"] = canonical_company_name(company.get("company") or "")
        result.append(company)

    return result
