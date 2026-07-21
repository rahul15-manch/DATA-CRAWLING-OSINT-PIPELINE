
from search.manager import get_search_manager
import json
import os
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import config
from discovery.company_discovery import discover_companies, quality_penalty
from discovery.contact_discovery import discover_contact
from extraction.page_extractor import extract_from_website
import utils.stats_tracker as stats
from utils.constants import (
    DECISION_MAKER_SCORES,
    HARD_REJECT_PENALTY_THRESHOLD,
    INFORMATIONAL_TITLE_TERMS,
    NON_COMPANY_DOMAINS,
)
from utils.source_ranker import get_source_score
from utils.validators import is_valid_person_record


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


def validate_lead(company: dict, extracted: dict) -> tuple:
    """
    Pre-card lead validation stage (Task 10 & 5).

    Returns
    -------
    (True, None)           — lead is valid, proceed to card creation
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

    # 8. Decision Maker Score (up to 15 points)
    max_dm_score = max(
        (p.get("decision_maker_score", 0) for p in people),
        default=0
    )
    score += 15.0 * (max_dm_score / 100.0)

    # 9. Business Source Score (up to 15 points)
    source_score = get_source_score(company.get("source", ""))
    score += 15.0 * (source_score / 100.0)

    # 10. Company Qualification Score (up to 10 points)
    penalty = quality_penalty(company)
    qualification_score = max(0, 100 - penalty)
    score += 10.0 * (qualification_score / 100.0)

    return int(round(score))


def _lead_quality_label(score: int) -> str:
    """Map a numeric confidence score to a human-readable quality tier."""
    if score >= 70:
        return "High"
    if score >= 40:
        return "Medium"
    return "Low"


# ─────────────────────────────────────────────────────────────────────────────
# Lead Card builder
# ─────────────────────────────────────────────────────────────────────────────

def build_lead_card(company: dict, keyword: str = "") -> dict | None:
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

    if website:
        if company.get("classification") == "UNKNOWN":
            # ── Task 15: Homepage Evaluation Budget ──
            if stats.get().get("funnel_homepage_evaluated", 0) >= getattr(config, "HOMEPAGE_EVAL_BUDGET", 10):
                print(f"[pipeline] Skipping homepage evaluation for {company.get('company')!r} — budget exhausted.")
                return None

            stats.increment("funnel_homepage_evaluated")
            
            from extraction.page_extractor import fetch_page
            homepage_html = fetch_page(website)
            if not homepage_html:
                return None
            from discovery.homepage_evaluator import evaluate_homepage
            new_classification = evaluate_homepage(homepage_html, website, "UNKNOWN", keyword=keyword, mode=search_mode.value)
            if new_classification == "REJECT":
                print(f"[pipeline] rejected UNKNOWN candidate {company.get('company')!r} after homepage evaluation.")
                return None
            company["classification"] = new_classification
            print(f"[pipeline] Upgraded UNKNOWN candidate {company.get('company')!r} to {new_classification}")

        extracted = extract_from_website(website, homepage_html=homepage_html)
        stats.increment("funnel_homepage_crawled")

        # Fallback site searches if extraction returned no emails/phones
        if website and not extracted.get("emails") and not extracted.get("phones"):
            from urllib.parse import urlparse
            domain = urlparse(website).netloc.lower()
            if domain.startswith("www."):
                domain = domain[4:]
            if domain:
                print(f"[pipeline] homepage extraction yielded no contacts. running fallback site searches for domain: {domain}")
                fallback_queries = [
                    f"site:{domain} email",
                    f"site:{domain} contact",
                    f"site:{domain} phone",
                    f"site:{domain} team",
                ]
                from search.manager import get_search_manager
                sm = get_search_manager()
                
                fallback_emails = []
                fallback_phones = []
                
                for q in fallback_queries:
                    try:
                        results = sm.search(q, max_results=3)
                        for res in results:
                            snippet = getattr(res, "snippet", "") or ""
                            from extraction.page_extractor import EMAIL_PATTERN, PHONE_CAPTURE_PATTERN, is_valid_phone
                            
                            found_emails = EMAIL_PATTERN.findall(snippet)
                            fallback_emails.extend(found_emails)
                            
                            found_phones = PHONE_CAPTURE_PATTERN.findall(snippet)
                            for phone in found_phones:
                                if is_valid_phone(phone.strip()):
                                    fallback_phones.append(phone.strip())
                    except Exception as e:
                        print(f"[pipeline] Fallback site search query '{q}' failed: {e}")
                        
                if fallback_emails:
                    extracted["emails"] = sorted(list(set(extracted.get("emails", []) + fallback_emails)))
                    print(f"[pipeline]   found emails from fallback site search: {extracted['emails']}")
                if fallback_phones:
                    extracted["phones"] = sorted(list(set(extracted.get("phones", []) + fallback_phones)))
                    print(f"[pipeline]   found phones from fallback site search: {extracted['phones']}")
    else:
        extracted = {
            "contact_page": None,
            "about_page": None,
            "team_page": None,
            "emails": [],
            "phones": [],
            "social_links": {},
            "people": [],
            "company_type": "Unknown",
            "industry_detected": "Unknown",
            "meta_description": "",
        }

    raw_people = list(extracted.get("people", []))
    emails = list(extracted.get("emails", []))

    # ── Contact discovery fallback ────────────────────────────────────────
    # Optimize contact discovery to only run when:
    # 1. Company website is present.
    # 2. emails list is empty (no email has been extracted yet).
    if website and not emails and not raw_people:
        sm = get_search_manager()
        if sm.providers_available():
            contact = discover_contact(company.get("company") or "")
            if contact.get("contact_name"):
                raw_people.append({
                    "name": contact.get("contact_name"),
                    "designation": contact.get("designation"),
                    "linkedin": contact.get("linkedin"),})
            if contact.get("email"):
                emails.append(contact["email"])
                emails = sorted(set(emails))
        else:
            print(f"[pipeline] Skipping contact discovery for {company.get('company')!r} — providers exhausted.")

    # ── Final Pattern Generation fallback ──
    if website and not emails:
        from urllib.parse import urlparse
        domain = urlparse(website).netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        if domain:
            from enrichment_leads import guess_emails_from_domain
            guessed = guess_emails_from_domain(domain)
            if guessed:
                emails = sorted(list(set(emails + guessed)))
                print(f"[pipeline]   Generated email patterns as final fallback: {guessed}")

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
    is_valid, rejection_reason = validate_lead(company, extracted)

    if not is_valid and not INCLUDE_LOW_QUALITY_LEADS:
        print(
            f"[pipeline] rejected lead {company.get('company')!r}"
            f": {rejection_reason}"
        )
        return None

    # ── Task 10: Completeness score ───────────────────────────────────────
    completeness_score = calculate_completeness_score(
        company, extracted, people, emails
    )

    # ── Task 6, 7 & 14: Build card with enrichment metadata ───────────────
    detected_industry = extracted.get("industry_detected")
    card = {
        "company_name":     company.get("company"),
        "website":          website,
        "linkedin":         company.get("linkedin"),
        "industry":         detected_industry if (detected_industry and detected_industry != "Unknown")
                            else (company.get("industry_detected") if company.get("industry_detected") != "Unknown"
                            else company.get("industry")),
        "location":         company.get("location"),
        "contact_page":     extracted.get("contact_page"),
        "about_page":       extracted.get("about_page"),
        "team_page":        extracted.get("team_page"),
        "emails":           emails,
        "phones":           extracted.get("phones", []),
        "social_links":     extracted.get("social_links", {}),
        "people":           people,
        "source":           company.get("source"),
        "confidence_score": company.get("relevance_score", completeness_score),  # SRE relevance score
        "lead_quality":     _lead_quality_label(company.get("relevance_score", completeness_score)),
        "company_type":     extracted.get("company_type", "Unknown"),
        "relevance_score":  company.get("relevance_score", 0),
        "relevance_tier":   company.get("relevance_tier", "LOW"),
        "relevance_info":   company.get("relevance_info", {}),
    }

    # Include rejection reason when the lead is kept but flagged low-quality
    if not is_valid:
        card["reason_if_rejected"] = rejection_reason

    return card


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline runner  (Tasks 12 & 13)
# ─────────────────────────────────────────────────────────────────────────────

def run_pipeline(keyword: str):
    """
    End-to-end lead generation pipeline with concurrent crawling (Task 13).

    Keyword → Discovery → Extraction → Validation → Lead Cards → JSON export
    """
    start_time = time.time()
    print(f"\nSearching for: {keyword}\n")

    # Discovering companies (Task 2 & 12 counts are handled inside)
    companies = discover_companies(keyword)
    print(f"Companies Found: {len(companies)}")

    leads = []
    max_workers = config.MAX_CRAWL_WORKERS

    # Task 13: concurrent crawling of discovered company websites
    print(f"Building Lead Cards in parallel using {max_workers} workers...")
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(build_lead_card, company, keyword): company
            for company in companies
        }
        for future in as_completed(futures):
            company = futures[future]
            try:
                lead = future.result()
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
                    is_high_quality = lead.get("lead_quality") in ("High", "Medium")
                    
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

    # ── Compute averages and timing ───────────────────────────────────────
    total_conf = sum(l.get("confidence_score", 0) for l in leads)
    avg_conf = (total_conf / len(leads)) if leads else 0.0

    execution_time = time.time() - start_time

    stats.set_value("avg_confidence", avg_conf)
    stats.set_value("execution_time_sec", execution_time)

    # Telemetry is handled centrally by run_pipeline.py -> dashboard.py

    # Summary
    high   = sum(1 for l in leads if l.get("lead_quality") == "High")
    medium = sum(1 for l in leads if l.get("lead_quality") == "Medium")
    low    = sum(1 for l in leads if l.get("lead_quality") == "Low")

    print("=" * 60)
    print("FINAL PIPELINE EXECUTION REPORT")
    print("=" * 60)
    print(f"Execution Time       : {execution_time:.2f}s")
    print(f"Leads Discovered     : {len(leads)}")
    print(f"Lead Quality Dist.   : High={high} | Medium={medium} | Low={low}")
    print(f"Output File          : {output_file}")
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

    return output_file



# ─────────────────────────────────────────────────────────────────────────────
# Entry-point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    keyword = input("Enter Keyword : ").strip()
    if keyword:
        run_pipeline(keyword)
    else:
        print("Keyword Required.")
