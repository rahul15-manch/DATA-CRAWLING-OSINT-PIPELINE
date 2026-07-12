"""
utils/source_ranker.py
======================
Source confidence scoring for company discovery (Task 4).

Higher score = more trustworthy source of company information.
Used when deduplicating records that refer to the same company.
"""

from utils.constants import DEFAULT_SOURCE_SCORE, SOURCE_CONFIDENCE_SCORES


def get_source_score(source: str) -> int:
    """
    Return an integer confidence score [0-100] for a named source.

    The lookup is case-insensitive and falls back to DEFAULT_SOURCE_SCORE
    for unrecognised sources.
    """
    key = (source or "").lower().strip()
    return SOURCE_CONFIDENCE_SCORES.get(key, DEFAULT_SOURCE_SCORE)


def best_company_record(existing: dict, candidate: dict) -> dict:
    """
    Compare two records for the same company and return the better one.

    Preference order
    ----------------
    1. Higher source confidence score
    2. More data completeness (website + LinkedIn)

    The losing record's website/LinkedIn are merged into the winner if the
    winner does not have them, so no data is ever silently discarded.
    """
    existing_score = get_source_score(existing.get("source", ""))
    candidate_score = get_source_score(candidate.get("source", ""))

    winner, loser = (
        (existing, candidate) if existing_score >= candidate_score
        else (candidate, existing)
    )

    # Preserve any data the loser has that the winner lacks
    merged = dict(winner)
    if not merged.get("website") and loser.get("website"):
        merged["website"] = loser["website"]
    if not merged.get("linkedin") and loser.get("linkedin"):
        merged["linkedin"] = loser["linkedin"]

    return merged
