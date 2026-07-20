"""
utils/enrichment.py
====================
Company type and industry detection from webpage content (Tasks 6 & 7).

Both functions are pure (side-effect-free) and operate on plain text
extracted from the page title, meta description, and page body.
"""

from utils.constants import COMPANY_TYPE_KEYWORDS, INDUSTRY_KEYWORD_MAP


def detect_company_type(text: str) -> str:
    """
    Infer company type (Task 6) from page text.

    Checks each COMPANY_TYPE_KEYWORDS entry in definition order;
    returns the first matching type, or "Unknown".

    Examples
    --------
    "AI-powered SaaS platform for …"       → "AI Startup"
    "Full-service digital marketing agency" → "Agency"
    "Industrial automation manufacturer"   → "Manufacturer"
    """
    lowered = (text or "").lower()
    for company_type, keywords in COMPANY_TYPE_KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            return company_type
    return "Unknown"


def detect_industry(text: str) -> str:
    """
    Infer industry (Task 7) from page text by scoring keyword density.

    Unlike detect_company_type(), this function scores ALL industries
    and returns the one with the most keyword hits — avoiding false
    positives from single-word overlaps.

    Examples
    --------
    "RPA software for enterprise automation workflows" → "Industrial Automation"
    "Cloud-native DevOps platform"                     → "Cloud Computing"
    "Healthcare AI for radiology"                      → "Artificial Intelligence"
    """
    lowered = (text or "").lower()
    if not lowered:
        return "Unknown"

    scores: dict[str, int] = {}
    for industry, keywords in INDUSTRY_KEYWORD_MAP.items():
        score = sum(1 for kw in keywords if kw in lowered)
        if score:
            scores[industry] = score

    if not scores:
        return "Unknown"

    return max(scores, key=scores.get)
