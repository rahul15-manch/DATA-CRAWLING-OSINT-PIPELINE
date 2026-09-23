import sys
import os
# Add the 'pillar1' subdirectory to sys.path so packages like 'search' and 'query' can be found
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "pillar1")))

from search.manager import get_search_manager
import json
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import config
from discovery.company_discovery import discover_companies, quality_penalty
from discovery.contact_discovery import discover_contact
from extraction.page_extractor import extract_from_website
from utils.deadline import Deadline, DeadlineExceeded
from search.exceptions import AllProvidersExhausted
import utils.stats_tracker as stats
from utils.constants import (
    DECISION_MAKER_SCORES,
    HARD_REJECT_PENALTY_THRESHOLD,
    INFORMATIONAL_TITLE_TERMS,
    NON_COMPANY_DOMAINS,
)
from utils.source_ranker import get_source_score
from utils.validators import is_valid_person_record
from utils.provenance import make_fact, SRC_SEARCH_RESULT_SNIPPET, SRC_CONTACT_PAGE_TEXT


# ── Pipeline behaviour flags ──────────────────────────────────────────────────

# Set True to include Low-quality / borderline leads in output (flagged).
# Set False to silently drop everything that fails validate_lead().
INCLUDE_LOW_QUALITY_LEADS = False


# ─────────────────────────────────────────────────────────────────────────────
# Task 8 — Decision Maker Ranking
# ─────────────────────────────────────────────────────────────────────────────

def calculate_decision_maker_score(designation: str) -> int:
    """
    Map a designation to its decision-maker priority score (Task 8).

    Scores range from 100 (Founder) to 20 (Support/min). Returns 0 if the
    designation has no match.
    """
    if not designation:
        return 0

    lowered = designation.lower().strip()
    # Check title matches in descending order of key length to match more specific substrings first
    sorted_scores = sorted(
        DECISION_MAKER_SCORES.items(),
        key=lambda x: len(x[0]),
        reverse=True
    )
    for title, score in sorted_scores:
        if title in lowered:
            return score

    return 20  # default minimum for any valid designation


# ─────────────────────────────────────────────────────────────────────────────
# Task 10 — Lead Validation Layer
# ─────────────────────────────────────────────────────────────────────────────
def _domain_token_from_url(url: str) -> str:
    """Extract registrable domain token (minimal, no external deps)."""
    from urllib.parse import urlparse
    domain = urlparse(url or "").netloc.lower()
    parts = [p for p in domain.split(".") if p and p != "www"]
    if not parts:
        return ""
    return parts[-2] if len(parts) >= 2 else parts[0]


def validate_lead(company: dict, extracted: dict, keyword: str = "") -> tuple[bool, str | None]:
    """
    Apply hard quality gates to a candidate company before creating a lead card.

    Returns
    -------
    (True, None)           — lead is accepted
    (False, reason: str)   — lead should be rejected; reason explains why
    """
    name = (company.get("company") or "").strip()
    website = company.get("website") or ""

    if len(name) < 2:
        return False, "company name too short"

    # Reject educational companies explicitly
    if extracted.get("company_type") == "Education Company":
        return False, "company classified as educational"

    lowered_name = name.lower()
    for term in INFORMATIONAL_TITLE_TERMS:
        if term in lowered_name:
            return False, f"company name contains informational term: '{term}'"

    token = _domain_token_from_url(website)
    if token and token in NON_COMPANY_DOMAINS:
        return False, f"website domain '{token}' is a blocked non-company site"

    penalty = quality_penalty(
        {**company, "website": website}
    )
    if penalty >= HARD_REJECT_PENALTY_THRESHOLD:
        return False, f"quality penalty {penalty} exceeds threshold"

    # Reject sparse records with no website and no contact channels
    has_contact = bool(
        website
        or company.get("emails")
        or extracted.get("emails")
        or company.get("phones")
        or extracted.get("phones")
        or company.get("linkedin")
    )
    if not has_contact:
        return False, "lead has no website or contact channels"

    # For entity queries, ensure company name aligns with target entity
    from query.intent_classifier import is_entity_query
    query_str = keyword or company.get("query") or company.get("industry") or ""
    if is_entity_query(query_str):
        import re
        kw_slug = re.sub(r"[^a-z0-9]", "", query_str.lower())
        comp_slug = re.sub(r"[^a-z0-9]", "", name.lower())
        if kw_slug and kw_slug not in comp_slug and comp_slug not in kw_slug:
            return False, f"company '{name}' does not match entity query '{query_str}'"

    return True, None


# ─────────────────────────────────────────────────────────────────────────────
# Task 10 — Company Completeness Score
# ─────────────────────────────────────────────────────────────────────────────

def calculate_completeness_score(
    company: dict,
    extracted: dict,
    people: list,
    emails: list,
) -> int:
    """
    Score lead completeness and business legitimacy from 0 to 100 (Task 10).

    Components (Weighted Sum)
    --------------------------
    1.  Website presence                      : 15 points
    2.  LinkedIn presence                     : 10 points
    3.  About page found                      :  5 points
    4.  Contact page found                    :  5 points
    5.  Team page found                       :  5 points
    6.  Emails found (non-empty)              : 10 points
    7.  Phones found (non-empty)              : 10 points
    8.  Decision Maker (max DM score scaled)   : up to 15 points
    9.  Business Source Score                 : up to 15 points
    10. Company Qualification (penalty scaled): up to 10 points
    ----------------------------------------------------------
    Total                                     : 100 points
    """
    score = 0.0

    # 1. Website presence (15 points)
    if company.get("website"):
        score += 15.0

    # 2. LinkedIn presence (10 points)
    if company.get("linkedin"):
        score += 10.0

    # 3-5. Sub-pages (5 points each)
    if extracted.get("about_page"):
        score += 5.0
    if extracted.get("contact_page"):
        score += 5.0
    if extracted.get("team_page"):
        score += 5.0

    # 6. Emails (10 points)
    if emails:
        score += 10.0

    # 7. Phones (10 points)
    if extracted.get("phones"):
        score += 10.0

    # 8. Decision Maker (max DM score scaled: up to 15 points)
    if people:
        max_dm = max((p.get("decision_maker_score", 0) for p in people), default=0)
        score += (max_dm / 100.0) * 15.0

    # 9. Business Source Score (up to 15 points)
    src_score = get_source_score(company.get("source") or "")
    score += (src_score / 100.0) * 15.0

    # 10. Company Qualification (penalty scaled: up to 10 points)
    penalty = quality_penalty(company)
    score += max(0.0, (1.0 - (penalty / 100.0)) * 10.0)

    return min(100.0, round(score, 1))


def _lead_quality_label(score: float) -> str:
    """Return quality label ('High', 'Medium', 'Low') based on score."""
    if score >= 70.0:
        return "High"
    elif score >= 40.0:
        return "Medium"
    return "Low"


def build_company(company: dict, keyword: str = "", global_deadline: Deadline | None = None) -> dict | None:
    """Worker entry-point: creates a per-company child deadline at worker start time."""
    if global_deadline and global_deadline.is_exceeded():
        print(f"[pipeline] Skipping worker for {company.get('company')!r} — global deadline exhausted before start.")
        return None

    # Create a company-scoped child properly bounded by the global deadline.
    company_budget_s = float(getattr(config, "COMPANY_DEADLINE_SECONDS", 40.0))
    company_deadline = global_deadline.child(company_budget_s) if global_deadline else Deadline(company_budget_s)
    return build_lead_card(company, keyword, deadline=company_deadline)


from urllib.parse import urlparse as _urlparse


def _extract_domain(website: str | None) -> str | None:
    """Extract bare domain from a URL without protocol or path."""
    if not website:
        return None
    try:
        netloc = _urlparse(website).netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc or None
    except Exception:
        return None


def _dq_level(value) -> str:
    """
    Return data quality level string: 'observed', 'verified', or 'not_found'.
    'observed'  — value exists and came from an actual source (not generated).
    'not_found' — extraction found nothing or value is purely generated.
    """
    if not value:
        return "not_found"
    if isinstance(value, list):
        if not value:
            return "not_found"
        if all(isinstance(v, dict) and v.get("source") == "generated_pattern" for v in value):
            return "not_found"
        return "observed"
    if isinstance(value, dict):
        if value.get("source") == "generated_pattern":
            return "not_found"
        return "observed"
    return "observed"


def verify_domain_evidence(company: dict, extracted: dict, keyword: str = "") -> tuple[str, str, list[str]]:
    """
    Evaluate corroborating evidence to verify domain ownership and identity match.

    Returns
    -------
    (identity_status, domain_status, evidence_signals)
    Where status is one of:
      - 'verified'          : Reachable + domain matches name + strong corroborating evidence (social links, LinkedIn, or title/meta)
      - 'identity_matched'  : Reachable + domain token matches name/query, but lacks external corroborating links
      - 'observed'          : Reachable + domain present from search/directory, but domain token does not match name
      - 'not_found'         : No website domain exists
    """
    website = company.get("website")
    if not website:
        if company.get("linkedin"):
            return "observed", "not_found", ["linkedin_company_observed_without_domain"]
        return "not_found", "not_found", []

    import re

    netloc = _urlparse(website).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    domain_parts = [p for p in netloc.split(".") if p]
    domain_token = domain_parts[0] if domain_parts else ""
    common_tlds = {"com", "co", "in", "org", "net", "io", "ai", "gov", "edu", "app", "dev", "biz", "info", "uk", "us", "de", "fr"}
    for part in domain_parts:
        if part not in common_tlds:
            domain_token = part
            break

    company_name = (company.get("company") or "").lower()
    name_slug = re.sub(r"[^a-z0-9]", "", company_name)
    kw_slug = re.sub(r"[^a-z0-9]", "", keyword.lower()) if keyword else ""

    evidence = ["domain_reachable"]
    clean_tok = re.sub(r"[^a-z0-9]", "", domain_token)

    # 1. Domain Token Match
    is_name_match = False
    if clean_tok:
        if name_slug and (clean_tok in name_slug or name_slug in clean_tok):
            is_name_match = True
            evidence.append("domain_token_matches_name")
        elif kw_slug and (clean_tok in kw_slug or kw_slug in clean_tok):
            is_name_match = True
            evidence.append("domain_token_matches_query")

    # 2. Corroborating Evidence: Social Profiles
    social_links = extracted.get("social_links", {})
    social_matched = False
    if isinstance(social_links, dict):
        for platform, s_url in social_links.items():
            if not s_url or not isinstance(s_url, str):
                continue
            s_lower = s_url.lower()
            if clean_tok and len(clean_tok) >= 3 and clean_tok in s_lower:
                evidence.append(f"social_profile_matches_domain:{platform}")
                social_matched = True
            elif name_slug and len(name_slug) >= 3 and name_slug in s_lower:
                evidence.append(f"social_profile_matches_name:{platform}")
                social_matched = True

    # 3. Corroborating Evidence: LinkedIn Profile Link
    linkedin_url = company.get("linkedin") or (social_links.get("linkedin") if isinstance(social_links, dict) else None)
    linkedin_matched = False
    if linkedin_url and isinstance(linkedin_url, str):
        l_lower = linkedin_url.lower()
        if clean_tok and len(clean_tok) >= 3 and clean_tok in l_lower:
            evidence.append("linkedin_matches_domain")
            linkedin_matched = True
        elif name_slug and len(name_slug) >= 3 and name_slug in l_lower:
            evidence.append("linkedin_matches_name")
            linkedin_matched = True

    # 4. Corroborating Evidence: Site Metadata & Description
    content_matched = False
    meta_desc = (extracted.get("meta_description") or extracted.get("description") or "").lower()
    if company_name and len(company_name) >= 3 and company_name in meta_desc:
        evidence.append("meta_description_matches_name")
        content_matched = True

    # 5. Corroborating Evidence: Discovered Subpages on Same Domain
    has_subpages = False
    if extracted.get("about_page") or extracted.get("contact_page"):
        evidence.append("official_subpages_discovered")
        has_subpages = True

    # Verification Decision
    corroboration_count = sum([social_matched, linkedin_matched, content_matched, has_subpages])

    if is_name_match and corroboration_count >= 1:
        status = "verified"
    elif is_name_match:
        status = "identity_matched"
    else:
        status = "observed"

    return status, status, evidence


def _dq_identity(company: dict, website: str | None) -> str:
    """Backward compatibility wrapper for identity quality."""
    if not website:
        return "not_found"
    if company.get("relevance_tier") == "HIGH":
        return "observed"
    return "not_found"


def _dq_domain(website: str | None, company: dict) -> str:
    """Backward compatibility wrapper for domain quality."""
    if website:
        return "observed"
    return "not_found"


def _build_lead_card_legacy(
    company: dict,
    keyword: str = "",
    deadline: Deadline | None = None,
    baseline_extracted: dict | None = None,
) -> dict | None:
    if deadline and deadline.is_exceeded():
        print(f"[pipeline] Skipping build_lead_card for {company.get('company')!r} — deadline exhausted. Retaining partial card.")
        return _build_minimal_partial_card(company, keyword, extracted=baseline_extracted)

    from config import SearchMode
    search_mode = getattr(config, "SEARCH_MODE", SearchMode.SEMANTIC)
    
    # ── Strict pre-rejection in EXACT mode to prevent expensive crawling ──
    if search_mode == SearchMode.EXACT:
        company_data = {
            "name": company.get("company") or "",
            "website_title": company.get("company") or "",
            "description": company.get("description") or "",
            "headline": company.get("company") or "",
            "about": "",
            "services": [],
            "positions": [],
            "industries": [company.get("industry")] if company.get("industry") else [],
            "technologies": [],
        }
        from discovery.semantic_ranking_engine import SemanticRanker
        ranker = SemanticRanker()
        if not ranker._is_literal_match(company_data, keyword):
            print(f"[pipeline] Exact mode: pre-rejecting company '{company.get('company')}' — literal match check failed.")
            return None

    website = company.get("website")
    homepage_html = None

    # Non-blocking website resolution attempt for LinkedIn-only leads
    if not website and company.get("linkedin") and company.get("company"):
        if not deadline or deadline.remaining() > 2.0:
            try:
                sm = get_search_manager()
                if sm.providers_available():
                    comp_name = company.get("company")
                    res = sm.search(f'"{comp_name}" official website', max_results=3, deadline=deadline)
                    for r in res:
                        r_url = getattr(r, "url", "") or ""
                        if r_url and not _is_platform_domain(r_url) and not is_rejected_lead_domain(r_url):
                            token = _domain_token_from_url(r_url)
                            name_clean = re.sub(r"[^a-z0-9]", "", comp_name.lower())
                            if token and (token in name_clean or name_clean in token or len(token) >= 4):
                                website = f"{_urlparse(r_url).scheme}://{_urlparse(r_url).netloc}"
                                company["website"] = website
                                print(f"[pipeline] Resolved website for LinkedIn lead {comp_name!r}: {website}")
                                break
            except Exception as e:
                print(f"[pipeline] Website resolution attempt failed for {company.get('company')!r}: {e}")

    if website:
        if deadline and deadline.is_exceeded():
            print(f"[pipeline] Deadline exhausted. Skipping homepage crawl for {company.get('company')!r}")
            return None

    if website:
        if company.get("classification") == "UNKNOWN":
            if getattr(config, "SERPAPI_PRIMARY_MODE", False):
                company["classification"] = "LIKELY_COMPANY"
            else:
                # ── Task 15: Homepage Evaluation Budget ──
                if stats.get().get("funnel_homepage_evaluated", 0) >= getattr(config, "HOMEPAGE_EVAL_BUDGET", 10):
                    print(f"[pipeline] Skipping homepage evaluation for {company.get('company')!r} — budget exhausted. Continuing with baseline extraction.")
                else:
                    stats.increment("funnel_homepage_evaluated")
                
                from extraction.page_extractor import fetch_page
                try:
                    homepage_html = fetch_page(website, deadline=deadline)
                except DeadlineExceeded:
                    print(f"[pipeline] DeadlineExceeded during homepage fetch for {company.get('company')!r}")
                    return None
                if not homepage_html:
                    return None
                from discovery.homepage_evaluator import evaluate_homepage
                new_classification = evaluate_homepage(homepage_html, website, "UNKNOWN", keyword=keyword, mode=search_mode.value)
                if new_classification == "REJECT":
                    print(f"[pipeline] rejected UNKNOWN candidate {company.get('company')!r} after homepage evaluation.")
                    return None
                company["classification"] = new_classification
                print(f"[pipeline] Upgraded UNKNOWN candidate {company.get('company')!r} to {new_classification}")

        if getattr(config, "SERPAPI_PRIMARY_MODE", False):
            if baseline_extracted is not None:
                extracted = baseline_extracted
            else:
                extracted = {
                    "contact_page": None, "about_page": None, "team_page": None,
                    "emails": [], "phones": [], "social_links": {}, "people": [],
                    "company_type": "Company", "industry_detected": company.get("industry_detected", "Unknown"),
                    "meta_description": company.get("snippet", ""),
                }
        elif baseline_extracted is not None:
            extracted = baseline_extracted
        else:
            try:
                extracted = extract_from_website(website, homepage_html=homepage_html, deadline=deadline)
            except DeadlineExceeded:
                print(f"[pipeline] DeadlineExceeded extracting from website for {company.get('company')!r}")
                extracted = {
                    "contact_page": None, "about_page": None, "team_page": None,
                    "emails": [], "phones": [], "social_links": {}, "people": [],
                    "company_type": "Unknown", "industry_detected": "Unknown", "meta_description": "",
                }

        stats.increment("funnel_homepage_crawled")

        # Fallback site searches if extraction returned no emails/phones and deadline permits
        if website and not extracted.get("emails") and not extracted.get("phones"):
            if deadline and deadline.remaining() > 3.0:
                from urllib.parse import urlparse
                domain = urlparse(website).netloc.lower()
                if domain.startswith("www."):
                    domain = domain[4:]
                if domain:
                    print(f"[pipeline] homepage extraction yielded no contacts. running fallback site searches for domain: {domain}")
                    fallback_queries = [
                        f"site:{domain} contact",
                        f"site:{domain} email",
                        f"{company.get('company')} support email",
                    ]
                    sm = get_search_manager()
                    
                    fallback_emails = []
                    fallback_emails_prov = []
                    fallback_phones = []
                    fallback_phones_prov = []
                    
                    for q in fallback_queries:
                        if deadline and deadline.is_exceeded():
                            break
                        try:
                            results = sm.search(q, max_results=3, deadline=deadline)
                            for res in results:
                                snippet = getattr(res, "snippet", "") or ""
                                res_url = getattr(res, "url", "") or ""
                                from extraction.page_extractor import (
                                    EMAIL_PATTERN, PHONE_CAPTURE_PATTERN, is_valid_phone,
                                    is_valid_email_candidate, is_disallowed_subpage_url,
                                    fetch_page, extract_emails,
                                )
                                
                                # 1. Snippet extraction
                                found_emails = EMAIL_PATTERN.findall(snippet)
                                for fe in found_emails:
                                    if is_valid_email_candidate(fe):
                                        fallback_emails.append(fe)
                                        fallback_emails_prov.append(make_fact(
                                            fe,
                                            SRC_SEARCH_RESULT_SNIPPET,
                                            source_url=res_url,
                                            observed=True,
                                            verified=False,
                                        ))
                                
                                # 2. Contact page fetch if on the same company domain (skipped in SERPAPI_PRIMARY_MODE)
                                if not getattr(config, "SERPAPI_PRIMARY_MODE", False) and res_url and domain in res_url.lower() and not is_disallowed_subpage_url(res_url):
                                    if deadline and deadline.remaining() > 3.0:
                                        try:
                                            contact_html = fetch_page(res_url, deadline=deadline)
                                            if contact_html:
                                                c_emails = extract_emails(contact_html)
                                                for ce in c_emails:
                                                    if is_valid_email_candidate(ce):
                                                        fallback_emails.append(ce)
                                                        fallback_emails_prov.append(make_fact(
                                                            ce,
                                                            SRC_CONTACT_PAGE_TEXT,
                                                            source_url=res_url,
                                                            observed=True,
                                                            verified=True,
                                                        ))
                                                if not extracted.get("contact_page") and "contact" in res_url.lower():
                                                    extracted["contact_page"] = res_url
                                        except Exception as fe_exc:
                                            print(f"[pipeline] Fallback fetch error for {res_url}: {fe_exc}")
                                
                                found_phones = PHONE_CAPTURE_PATTERN.findall(snippet)
                                for phone in found_phones:
                                    if is_valid_phone(phone.strip()):
                                        p_clean = phone.strip()
                                        fallback_phones.append(p_clean)
                                        fallback_phones_prov.append(make_fact(
                                            p_clean,
                                            SRC_SEARCH_RESULT_SNIPPET,
                                            source_url=res_url,
                                            observed=True,
                                            verified=False,
                                        ))
                        except Exception as e:
                            print(f"[pipeline] Fallback site search query '{q}' failed: {e}")
                            
                    if fallback_emails:
                        extracted["emails"] = sorted(list(set(extracted.get("emails", []) + fallback_emails)))
                        extracted.setdefault("emails_provenance", []).extend(fallback_emails_prov)
                        print(f"[pipeline]   found emails from fallback site search: {extracted['emails']}")
                    if fallback_phones:
                        extracted["phones"] = sorted(list(set(extracted.get("phones", []) + fallback_phones)))
                        extracted.setdefault("phones_provenance", []).extend(fallback_phones_prov)
                        print(f"[pipeline]   found phones from fallback site search: {extracted['phones']}")
    else:
        extracted = {
            "contact_page": None,
            "about_page": None,
            "team_page": None,
            "emails": [],
            "emails_provenance": [],
            "phones": [],
            "phones_provenance": [],
            "social_links": {},
            "people": [],
            "company_type": "Unknown",
            "industry_detected": "Unknown",
            "meta_description": "",
            "employees": None,
            "employees_provenance": None,
            "founded": None,
            "founded_provenance": None,
            "country": None,
            "country_provenance": None,
            "location": None,
            "location_provenance": None,
            "description": None,
        }

    raw_people = list(extracted.get("people", []))
    emails = list(extracted.get("emails", []))

    # ── Contact discovery fallback ────────────────────────────────────────
    if website and not emails and not raw_people:
        can_run = True
        if deadline:
            try:
                deadline.require(1.0)
            except DeadlineExceeded:
                can_run = False
                print(f"[pipeline] Contact discovery budget exhausted. Skipping for {company.get('company')!r}")
        if can_run:
            sm = get_search_manager()
            if sm.providers_available():
                contact = discover_contact(company.get("company") or "", deadline=deadline)
                if contact.get("contact_name"):
                    raw_people.append({
                        "name": contact.get("contact_name"),
                        "designation": contact.get("designation"),
                        "linkedin": contact.get("linkedin"),
                    })
                if contact.get("email"):
                    c_em = contact["email"]
                    emails.append(c_em)
                    emails = sorted(set(emails))
                    extracted.setdefault("emails_provenance", []).append(make_fact(
                        c_em,
                        SRC_SEARCH_RESULT_SNIPPET,
                        source_url=contact.get("linkedin") or "",
                        observed=True,
                        verified=False,
                    ))
            else:
                print(f"[pipeline] Skipping contact discovery for {company.get('company')!r} — providers exhausted.")

    # ── Pattern Generation Fallback (Saved separately to email_candidates) ──
    email_candidates = []
    if website and not emails:
        from urllib.parse import urlparse
        domain = urlparse(website).netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        if domain:
            from enrichment_leads import guess_emails_from_domain
            guessed = guess_emails_from_domain(domain)
            if guessed:
                for g in guessed:
                    email_candidates.append({
                        "email": g,
                        "source": "generated_pattern",
                        "verified": False,
                    })
                print(f"[pipeline] Generated {len(email_candidates)} email candidate patterns for {domain}")

    if emails or raw_people or extracted.get("phones"):
        stats.increment("funnel_contacts_extracted")
        from query.expansion import record_query_outcome
        q = company.get("query") or company.get("industry") or ""
        src = (company.get("source") or "google").lower()
        provider_map = {
            "linkedin": "linkedin",
            "clutch": "clutch",
            "goodfirms": "goodfirms",
            "google": "google_html",
            "bing": "bing",
            "brave": "brave",
            "github": "github",
        }
        provider_name = provider_map.get(src, "google_html")
        cnt = len(emails) + len(raw_people) + (1 if extracted.get("phones") else 0)
        record_query_outcome(q, "contact_found", result_count=cnt, provider=provider_name)

    # ── Task 8: Score each person record ──────────────────────────────────
    people = []
    for p in raw_people:
        p_copy = dict(p)
        p_copy["decision_maker_score"] = calculate_decision_maker_score(
            p_copy.get("designation", "")
        )
        people.append(p_copy)

    # ── Task 10: Pre-card validation ──────────────────────────────────────
    is_valid, rejection_reason = validate_lead(company, extracted, keyword=keyword)

    allow_partial = bool(
        company.get("linkedin")
        or company.get("verification_status") == "partial"
        or company.get("discovery_stage") == "PARTIAL"
        or extracted.get("emails")
        or extracted.get("phones")
        or website
        or company.get("source_url")
    )
    if not is_valid and not INCLUDE_LOW_QUALITY_LEADS:
        is_hard_reject = (
            len((company.get("company") or "").strip()) < 2
            or any(t in (company.get("company") or "").lower() for t in INFORMATIONAL_TITLE_TERMS)
            or (_domain_token_from_url(website) in NON_COMPANY_DOMAINS if website else False)
        )
        if not is_hard_reject and len((company.get("company") or "").strip()) >= 2:
            print(
                f"[pipeline] retaining partial lead {company.get('company')!r} despite validation flag"
                f": {rejection_reason}"
            )
            company["verification_status"] = "partial"
        else:
            print(
                f"[pipeline] rejected lead {company.get('company')!r}"
                f": {rejection_reason}"
            )
            return None

    # ── Evidence-based Domain Verification ─────────────────────────────────
    identity_status, domain_status, domain_evidence = verify_domain_evidence(
        company, extracted, keyword=keyword
    )

    # ── Task 10: Completeness score & Calibrated Confidence ────────────────
    completeness_score = calculate_completeness_score(
        company, extracted, people, emails
    )

    # Scale completeness by domain verification level
    multiplier = {
        "verified": 1.0,
        "identity_matched": 0.85,
        "observed": 0.65,
        "not_found": 0.30,
    }.get(identity_status, 0.50)

    calibrated_confidence = int(round(completeness_score * multiplier))

    # ── Task 6, 7 & 14: Build card with enrichment metadata and provenance ──
    detected_industry = extracted.get("industry_detected")

    emails_provenance = list(extracted.get("emails_provenance", []))
    phones_provenance = list(extracted.get("phones_provenance", []))

    flat_emails = sorted(list(set(emails)))
    flat_phones = sorted(list(set(extracted.get("phones", []))))

    card = {
        # ── Identity ──────────────────────────────────────────
        "company_name":        company.get("company"),
        "website":             website,
        "domain":              _extract_domain(website),
        "linkedin":            company.get("linkedin"),
        "company_linkedin":    company.get("linkedin"),
        # ── Contact ───────────────────────────────────────────
        "emails":              flat_emails,
        "emails_provenance":   emails_provenance,
        "email_candidates":    email_candidates,
        "phones":              flat_phones,
        "phones_provenance":   phones_provenance,
        "phone_found":         bool(flat_phones),
        "email_found":         bool(flat_emails),
        "decision_maker_found": bool(any(isinstance(p, dict) and p.get("designation") for p in people)),
        # ── Company Metadata ──────────────────────────────────
        "industry":            detected_industry if (detected_industry and detected_industry != "Unknown")
                               else (company.get("industry_detected") if company.get("industry_detected") != "Unknown"
                               else company.get("industry")),
        "location":            extracted.get("location") or company.get("location") or None,
        "location_provenance": extracted.get("location_provenance"),
        "country":             extracted.get("country") or None,
        "country_provenance":  extracted.get("country_provenance"),
        "employees":           extracted.get("employees") or None,
        "employees_provenance":extracted.get("employees_provenance"),
        "founded":             extracted.get("founded") or None,
        "founded_provenance":  extracted.get("founded_provenance"),
        "description":         extracted.get("description") or None,
        "company_type":        extracted.get("company_type", "Unknown"),
        "tech_stack":          extracted.get("tech_stack", []),
        # ── People ────────────────────────────────────────────
        "people":              people,
        # ── Sub-pages & Links ─────────────────────────────────
        "contact_page":        extracted.get("contact_page"),
        "about_page":          extracted.get("about_page"),
        "team_page":           extracted.get("team_page"),
        "social_links":        extracted.get("social_links", {}),
        # ── Data Quality & Provenance Summary ─────────────────
        "data_quality": {
            "identity":    identity_status,
            "domain":      domain_status,
            "email":       _dq_level(emails_provenance),
            "phone":       _dq_level(phones_provenance),
            "location":    _dq_level(extracted.get("location_provenance")),
            "employees":   _dq_level(extracted.get("employees_provenance")),
            "founded":     _dq_level(extracted.get("founded_provenance")),
            "people":      _dq_level(people),
            "description": "observed" if extracted.get("description") else "not_found",
        },
        "domain_verification": {
            "status":   identity_status,
            "domain":   _extract_domain(website),
            "evidence": domain_evidence,
        },
        "missing_fields": [
            field for field, val in {
                "email":     emails_provenance,
                "phone":     phones_provenance,
                "employees": extracted.get("employees_provenance"),
                "founded":   extracted.get("founded_provenance"),
                "location":  extracted.get("location_provenance"),
                "people":    people,
            }.items() if not val
        ],
        # ── Search & Relevance ────────────────────────────────
        "source":              company.get("source"),
        "source_url":          company.get("source_url") or website or "",
        "confidence_score":    calibrated_confidence,
        "lead_quality":        _lead_quality_label(calibrated_confidence),
        "verification_status": company.get("verification_status") or ("verified" if identity_status == "verified" else "partial"),
        "qualification_reason": company.get("qualification_reason"),
        "relevance_score":     company.get("relevance_score", 0),
        "relevance_tier":      company.get("relevance_tier", "LOW"),
        "relevance_info":      company.get("relevance_info", {}),
        "contact_completeness": {
            "email": 100 if flat_emails else 0,
            "phone": 100 if flat_phones else 0,
            "contact_page": 100 if extracted.get("contact_page") else 0,
        },
        "lead_actionability": {
            "company_name": 100 if company.get("company") else 0,
            "usable_phone": 100 if flat_phones else 0,
            "usable_email": 100 if flat_emails else 0,
            "decision_maker": 100 if any(p.get("designation") for p in people) else 0,
        },
    }

    # Include rejection reason when the lead is kept but flagged low-quality
    if not is_valid:
        card["reason_if_rejected"] = rejection_reason
        card["verification_status"] = "partial"
        card["lead_quality"] = "Low"

    return card


def _build_minimal_partial_card(company: dict, keyword: str = "", extracted: dict | None = None) -> dict:
    """Return a minimal honest partial card when no enrichment time remains or after partial enrichment."""
    website = company.get("website")
    linkedin = company.get("linkedin")
    name = company.get("company") or keyword or "Unknown Company"
    ext = extracted or {}

    flat_emails = sorted(list(set(ext.get("emails") or company.get("emails") or [])))
    flat_phones = sorted(list(set(ext.get("phones") or company.get("phones") or [])))
    people = list(ext.get("people") or company.get("people") or [])
    employees = ext.get("employees") or company.get("employees") or None
    contact_page = ext.get("contact_page") or company.get("contact_page") or None
    location = ext.get("location") or company.get("location") or None
    industry = ext.get("industry_detected") or company.get("industry") or None
    description = ext.get("description") or company.get("description") or None
    source_url = company.get("source_url") or website or ""

    return {
        "company_name": name,
        "website": website,
        "domain": _extract_domain(website),
        "linkedin": linkedin,
        "company_linkedin": linkedin,
        "emails": flat_emails,
        "email_candidates": list(ext.get("email_candidates") or []),
        "phones": flat_phones,
        "tech_stack": list(ext.get("tech_stack") or []),
        "people": people,
        "employees": employees,
        "social_links": ext.get("social_links") or {},
        "contact_page": contact_page,
        "about_page": ext.get("about_page") or None,
        "team_page": ext.get("team_page") or None,
        "industry": industry,
        "location": location,
        "country": ext.get("country") or company.get("country") or None,
        "description": description,
        "company_type": ext.get("company_type") or company.get("company_type") or "Company",
        "source": company.get("source"),
        "source_url": source_url,
        "phone_found": bool(flat_phones),
        "email_found": bool(flat_emails),
        "decision_maker_found": bool(any(isinstance(p, dict) and p.get("designation") for p in people)),
        "confidence_score": 50 if (flat_emails or flat_phones or people) else 0,
        "lead_quality": "Medium" if (flat_emails or flat_phones) else "Low",
        "verification_status": company.get("verification_status") or "partial",
        "qualification_reason": company.get("qualification_reason") or "partial_lead",
        "relevance_score": company.get("relevance_score", 0),
        "relevance_tier": company.get("relevance_tier", "LOW"),
        "relevance_info": company.get("relevance_info", {}),
        "data_quality": {
            "identity": "observed" if name else "not_found",
            "domain": "observed" if website else "not_found",
            "email": "observed" if flat_emails else "not_found",
            "phone": "observed" if flat_phones else "not_found",
            "location": "observed" if location else "not_found",
            "employees": "observed" if employees else "not_found",
            "founded": "not_found",
            "people": "observed" if people else "not_found",
            "description": "observed" if description else "not_found",
        },
        "domain_verification": {
            "status": "observed" if website else "not_found",
            "domain": _extract_domain(website),
            "evidence": ["partial_lead_retained"],
        },
        "missing_fields": [
            f for f in ["email", "phone", "employees", "founded", "location", "people"]
            if (f == "email" and not flat_emails) or (f == "phone" and not flat_phones) or (f == "people" and not people) or (f == "employees" and not employees) or (f == "location" and not location) or f == "founded"
        ],
        "contact_completeness": {"email": 100 if flat_emails else 0, "phone": 100 if flat_phones else 0, "contact_page": 100 if contact_page else 0},
        "lead_actionability": {
            "company_name": 100 if name else 0,
            "usable_phone": 100 if flat_phones else 0,
            "usable_email": 100 if flat_emails else 0,
            "decision_maker": 100 if any(isinstance(p, dict) and p.get("designation") for p in people) else 0,
        },
    }


def build_lead_card(company: dict, keyword: str = "", deadline: Deadline | None = None) -> dict | None:
    """Build a lead card through the Phase 1 enrichment orchestration layer."""
    if deadline and deadline.is_exceeded():
        print(f"[pipeline] Deadline exhausted before enrichment for {company.get('company')!r}. Retaining partial card.")
        return _build_minimal_partial_card(company, keyword)

    from enrichment.orchestrator import EnrichmentOrchestrator

    try:
        context = EnrichmentOrchestrator.context_from_company(
            company,
            keyword=keyword,
            deadline=deadline,
        )
        result = EnrichmentOrchestrator(
            extractor=extract_from_website,
            legacy_builder=_build_lead_card_legacy,
        ).run(context)
        if result is None:
            return _build_minimal_partial_card(company, keyword, extracted=context.baseline_extraction)
        return result
    except Exception as exc:
        print(f"[pipeline] Enrichment orchestrator failed; using legacy builder: {exc}")
        try:
            legacy = _build_lead_card_legacy(company, keyword, deadline)
            if legacy is not None:
                return legacy
        except Exception:
            pass
        ext = context.baseline_extraction if "context" in locals() and hasattr(context, "baseline_extraction") else None
        return _build_minimal_partial_card(company, keyword, extracted=ext)


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline runner  (Tasks 12 & 13)
# ─────────────────────────────────────────────────────────────────────────────

def run_pipeline(keyword: str, run_deadline: Deadline | None = None):
    """
    End-to-end lead generation pipeline with concurrent crawling (Task 13).

    Keyword → Discovery → Extraction → Validation → Lead Cards → JSON export
    """
    if not run_deadline:
        run_deadline = Deadline(float(getattr(config, "MAX_RUNTIME", 120.0)))

    start_time = time.monotonic()
    print(f"\nSearching for: {keyword}\n")

    discovery_budget_s = float(getattr(config, "DISCOVERY_DEADLINE_SECONDS", 55.0))
    discovery_deadline = run_deadline.child(discovery_budget_s)
    discovery_started = time.monotonic()
    try:
        companies = discover_companies(keyword, deadline=discovery_deadline)
    except AllProvidersExhausted as e:
        print("DISCOVERY UNAVAILABLE: No providers available or all providers exhausted. Aborting pipeline.")
        return []

    discovery_elapsed = time.monotonic() - discovery_started
    stats.set_value("discovery_runtime_sec", round(discovery_elapsed, 3))

    # If discovery returned no validated companies but a partial snapshot exists,
    # surface the partial file and abort to avoid continuing the pipeline silently.
    if not companies:
        try:
            import glob
            safe = keyword.replace(" ", "_").replace("/", "_").replace("\\", "_").lower().strip("_") or "partial"
            matches = glob.glob(os.path.join("output", f"partial_{safe}_*.json"))
            if matches:
                # Prefer the newest file
                matches.sort(key=os.path.getmtime, reverse=True)
                print(f"DISCOVERY FINISHED WITH NO VALID COMPANIES. Partial snapshot available: {matches[0]}")
                return []
        except Exception:
            pass
        return []
    print(f"Companies Found: {len(companies)}")

    leads = []
    max_workers = min(
        int(config.MAX_CRAWL_WORKERS),
        int(getattr(config, "MAX_COMPANIES_IN_FLIGHT", config.MAX_CRAWL_WORKERS)),
    )

    # Task 13: concurrent crawling of discovered company websites
    print(f"Building Lead Cards in parallel using {max_workers} workers...")
    enrichment_started = time.monotonic()
    executor = ThreadPoolExecutor(max_workers=max_workers)
    try:
        futures = {
            executor.submit(build_company, company, keyword, run_deadline): company
            for company in companies
        }
        for future in as_completed(futures):
            if run_deadline and run_deadline.is_exceeded():
                print(f"[pipeline] Global run deadline exceeded ({run_deadline.remaining():.1f}s remaining). Halting lead generation loop.")
                break
            company = futures[future]
            try:
                per_worker_timeout = max(0.5, run_deadline.remaining()) if run_deadline else 40.0
                lead = future.result(timeout=per_worker_timeout)
                stats.increment("companies_crawled")
                if lead is not None:
                    leads.append(lead)
                    stats.increment("lead_cards_generated")
                    stats.increment("funnel_leads_exported")
                    # Update search manager provider stats for ranking
                    from search.manager import get_search_manager
                    sm = get_search_manager()
                    source = company.get("source")
                    if source in sm.stats:
                        sm.stats[source].leads_discovered += 1

                    # Log feedback for SRE weight optimization and B2B ontology learning
                    sre_info = company.get("relevance_info", {})
                    matched = sre_info.get("matched_signals", [])
                    techs = sre_info.get("technologies", [])
                    prods = sre_info.get("products", [])
                    is_high_quality = lead.get("relevance_tier") in ("HIGH", "MEDIUM") or lead.get("confidence_score", 0) >= 60
                    
                    from semantic.semantic_learning import record_learning_feedback
                    record_learning_feedback(keyword, techs, prods, was_successful=is_high_quality)

                    if matched:
                        from discovery.semantic_ranking_engine import record_feedback
                        record_feedback("reward" if is_high_quality else "penalize", matched)
                else:
                    # Penalize matched signals of the rejected candidate
                    sre_info = company.get("relevance_info", {})
                    matched = sre_info.get("matched_signals", [])
                    techs = sre_info.get("technologies", [])
                    prods = sre_info.get("products", [])
                    
                    from semantic.semantic_learning import record_learning_feedback
                    record_learning_feedback(keyword, techs, prods, was_successful=False)

                    if matched:
                        from discovery.semantic_ranking_engine import record_feedback
                        record_feedback("penalize", matched)
            except Exception as exc:
                print(
                    f"Error building lead card for {company.get('company')!r}:"
                    f" {exc}"
                )
    finally:
        executor.shutdown(wait=True, cancel_futures=True)

    stats.set_value("enrichment_runtime_sec", round(time.monotonic() - enrichment_started, 3))

    # Apply batch weight learning exactly once at the end of the run
    from discovery.semantic_ranking_engine import apply_batch_learning
    apply_batch_learning()
    from semantic.semantic_learning import apply_ontology_learning
    apply_ontology_learning()

    # ── Write output ──────────────────────────────────────────────────────
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Sanitize keyword to prevent directory traversal or file path issues
    filename = keyword.replace(" ", "_").replace("/", "_").replace("\\", "_").lower()
    filename = filename.strip("_")
    if not filename:
        filename = "lead"
        
    output_file = os.path.join(
        config.RAW_OUTPUT_FOLDER,
        f"{filename}_{timestamp}.json",
    )
    
    # Ensure the parent directory structure of the output file exists
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(leads, f, indent=4, ensure_ascii=False)

    discovery_report = stats.get().get("discovery_report")
    if discovery_report:
        report_file = os.path.splitext(output_file)[0] + "_discovery_report.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(discovery_report, f, indent=2, ensure_ascii=False)
        print(f"Discovery Attribution : {report_file}")

    # ── Compute averages and timing ───────────────────────────────────────
    total_conf = sum(l.get("confidence_score", 0) for l in leads)
    avg_conf = (total_conf / len(leads)) if leads else 0.0

    execution_time = time.monotonic() - start_time

    stats.set_value("avg_confidence", avg_conf)
    stats.set_value("execution_time_sec", execution_time)

    # Telemetry is handled centrally by run_pipeline.py -> dashboard.py

    # ── Strict Coverage & Benchmark Metrics ───────────────────────────────
    total_companies = len(companies)
    total_leads = len(leads)

    # 1. Observed Phone Coverage (must exist, pass validation/normalization, and be observed)
    leads_with_phone = sum(
        1 for l in leads
        if bool(l.get("phones")) and any(
            bool(p and len(str(p).strip()) >= 7) for p in l.get("phones", [])
        )
    )

    # 2. Observed Email Coverage (must exist and be observed from source, excluding generated candidates)
    leads_with_email = sum(
        1 for l in leads
        if bool(l.get("emails")) and any(
            isinstance(e, str) and "@" in e for e in l.get("emails", [])
        )
    )

    # 3. Both Phone and Email
    leads_with_both = sum(
        1 for l in leads
        if bool(l.get("phones")) and bool(l.get("emails"))
    )

    # 4. Strict Decision Maker Coverage (must have name + explicit designation)
    def _has_strict_dm(lead):
        for p in (lead.get("people") or []):
            if isinstance(p, dict):
                name = (p.get("name") or "").strip()
                desig = (p.get("designation") or "").strip()
                if name and desig and len(name) >= 3 and len(desig) >= 2:
                    return True
        return False

    leads_with_dm = sum(1 for l in leads if _has_strict_dm(l))

    phone_pct = (leads_with_phone / total_leads * 100) if total_leads else 0.0
    email_pct = (leads_with_email / total_leads * 100) if total_leads else 0.0
    both_pct = (leads_with_both / total_leads * 100) if total_leads else 0.0
    dm_pct = (leads_with_dm / total_leads * 100) if total_leads else 0.0

    stats.set_value("companies_found", total_companies)
    stats.set_value("lead_cards_created", total_leads)
    stats.set_value("leads_returned", total_leads)
    stats.set_value("leads_with_phone", leads_with_phone)
    stats.set_value("leads_with_email", leads_with_email)
    stats.set_value("leads_with_both", leads_with_both)
    stats.set_value("leads_with_decision_maker", leads_with_dm)
    stats.set_value("phone_coverage_pct", round(phone_pct, 1))
    stats.set_value("email_coverage_pct", round(email_pct, 1))
    stats.set_value("both_coverage_pct", round(both_pct, 1))
    stats.set_value("decision_maker_coverage_pct", round(dm_pct, 1))

    observed_id = sum(1 for l in leads if l.get("data_quality", {}).get("identity") in ("verified", "observed"))

    print("=" * 60)
    print("FINAL PIPELINE EXECUTION REPORT")
    print("=" * 60)
    print(f"Execution Time            : {execution_time:.2f}s")
    print(f"Companies Found           : {total_companies}")
    print(f"Lead Cards Created        : {total_leads}")
    print(f"Leads with Phone          : {leads_with_phone}/{total_leads} ({phone_pct:.1f}%)")
    print(f"Leads with Email          : {leads_with_email}/{total_leads} ({email_pct:.1f}%)")
    print(f"Leads with Both           : {leads_with_both}/{total_leads} ({both_pct:.1f}%)")
    print(f"Leads with Decision Maker : {leads_with_dm}/{total_leads} ({dm_pct:.1f}%)")
    print(f"Phone Coverage %          : {phone_pct:.1f}%")
    print(f"Email Coverage %          : {email_pct:.1f}%")
    print(f"Both Coverage %           : {both_pct:.1f}%")
    print(f"Decision Maker Coverage % : {dm_pct:.1f}%")
    print(f"Identified Entities       : {observed_id}/{total_leads}")
    print(f"Output File               : {output_file}")
    print("=" * 60 + "\n")

    # Commercial Intent Sanity Check Metric
    try:
        from search.manager import is_high_priority_query
        is_commercial = is_high_priority_query(keyword)
    except Exception:
        is_commercial = False

    if is_commercial and len(companies) >= 5:
        acceptance_rate = (len(leads) / len(companies))
        if acceptance_rate < 0.05:
            print("!" * 60)
            print("WARNING: HIGH COMMERCIAL INTENT QUERY YIELDED VERY LOW ACCEPTANCE!")
            print(f"  Query '{keyword}' has strong B2B/commercial intent classification,")
            print(f"  but only {len(leads)} out of {len(companies)} discovered pages ({acceptance_rate*100:.1f}%) were accepted.")
            print("  This pattern suggests a potential scorer mismatch or ontology mapping issue.")
            print("  Please check if company homepages are being filtered out under 'semantic_low_score'.")
            print("!" * 60 + "\n")

    return leads



# ─────────────────────────────────────────────────────────────────────────────
# Entry-point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    keyword = input("Enter Keyword : ").strip()
    if keyword:
        run_pipeline(keyword)
    else:
        print("Keyword Required.")
