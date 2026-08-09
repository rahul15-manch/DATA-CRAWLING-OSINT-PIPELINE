from __future__ import annotations
from typing import Any

def compute_lead_score(lead: dict[str, Any]) -> int:
    if not lead:
        return 0
    score = 0
    if lead.get('emails'):
        score += 15
    if lead.get('phones'):
        score += 10
    if lead.get('people'):
        score += 5
    socials = lead.get('social_links') or {}
    score += min(20, len(socials) * 5)
    techs = lead.get('tech_stack') or []
    score += min(20, len(techs) * 5)
    if lead.get('description') or lead.get('meta_description'):
        score += 5
    if lead.get('industry') or (lead.get('industry_detected') and lead.get('industry_detected') != 'Unknown'):
        score += 5
    if lead.get('employees') or lead.get('founded') or lead.get('country'):
        score += 5
    if lead.get('source'):
        score += 10
    if lead.get('contact_page') or lead.get('about_page'):
        score += 5
    return min(100, score)
