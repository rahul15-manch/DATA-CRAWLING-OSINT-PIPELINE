"""
discovery/company_discovery.py
================================
Discovers and qualifies companies from raw search results.

Changes in this revision (v3)
------------------------------
Task 2  — Pagination loop: keep fetching next pages until TARGET_COMPANIES
           is reached or all queries are exhausted (MAX_SEARCH_PAGES pages).
Task 4  — Source confidence: when the same company appears from multiple
           sources, the record from the highest-confidence source wins.
           source_ranker.best_company_record() handles the merge.
Task 5  — Better company qualification: educational URL path checker,
           extended informational title terms (all from constants).
Task 11 — Company name normalization: normalizer.normalize_companies()
           collapses "IBM India", "IBM Corporation", "IBM" → "IBM".
Task 12 — Statistics: all counters are reported to utils.stats_tracker.
Task 12 (code quality) — All constant sets imported from utils.constants
           (no local duplication). quality_penalty() applied inside
           discover_companies(). dedupe_companies() wired at the end.
"""

import json
import logging
import os
import time
import sys
import re
from collections import defaultdict
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor

DEBUG = os.getenv("DISCOVERY_DEBUG", "false").lower() == "true"

# Force UTF-8 output on Windows to prevent UnicodeEncodeError
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

import config
from discovery.search_backend import run_search
from query.dork_generator import generate_search_tasks
from parser.parser import dedupe_companies

import utils.stats_tracker as stats
from utils.constants import (
    BUSINESS_DOMAIN_SUFFIXES,
    BUSINESS_HINTS,
    DOMAIN_NAME_OVERRIDES,
    HARD_REJECT_PENALTY_THRESHOLD,
    INFORMATIONAL_TITLE_TERMS,
    NON_COMPANY_DOMAINS,
    PLATFORM_DOMAINS,
    QUALITY_PENALTIES,
    SOURCE_DOMAIN_MAP,
    TITLE_NOISE_PARTS,
)
from utils.source_ranker import best_company_record, get_source_score
from utils.normalizer import normalize_companies
from utils.validators import is_lead_url_valid


# ─────────────────────────────────────────────────────────────────────────────
# Internal text helpers
# ─────────────────────────────────────────────────────────────────────────────

def _clean_text(value: str) -> str:
    """Normalize whitespace and strip surrounding punctuation."""
    value = re.sub(r"\s+", " ", value or "").strip()
    return value.strip(" -|:.,")


def _title_contains_informational_term(title: str) -> bool:
    """Return True when a result title looks like an article or learning page."""
    lowered = (title or "").lower()
    return any(term in lowered for term in INFORMATIONAL_TITLE_TERMS)


def _title_has_business_signal(title: str) -> bool:
    """Return True when a title contains language commonly used by companies."""
    lowered = (title or "").lower()
    return any(hint in lowered for hint in BUSINESS_HINTS)


def _split_title_candidates(title: str) -> list:
    """Split a search result title into possible company-name candidates."""
    title = _clean_text(title)
    if not title:
        return []
    pattern = r"\s+\|\s+|\s+[-–]\s+|\s+:\s+|:\s+"
    return [_clean_text(part) for part in re.split(pattern, title) if _clean_text(part)]


# ─────────────────────────────────────────────────────────────────────────────
# Domain helpers
# ─────────────────────────────────────────────────────────────────────────────

def _domain_token(url: str) -> str:
    """Extract an approximate registrable domain token without external deps."""
    domain = urlparse(url or "").netloc.lower()
    if not domain:
        return ""
    parts = [part for part in domain.split(".") if part and part != "www"]
    if not parts:
        return ""
    # Handle  co.uk / com.au / co.in  style ccSLD
    country_tld = len(parts[-1]) == 2
    second_level_tld = len(parts) >= 2 and parts[-2] in {
        "ac", "co", "com", "edu", "gov", "net", "org",
    }
    if len(parts) >= 3 and country_tld and second_level_tld:
        return parts[-3]
    return parts[-2] if len(parts) >= 2 else parts[0]


def _is_platform_domain(url: str) -> bool:
    """Return True when the URL belongs to a known listing/directory platform."""
    domain = urlparse(url or "").netloc.lower()
    return any(platform in domain for platform in PLATFORM_DOMAINS)


def _domain_suffix(url: str) -> str:
    """Return the TLD for lightweight domain-suffix validation."""
    domain = urlparse(url or "").netloc.lower()
    parts = [p for p in domain.split(".") if p]
    return parts[-1] if parts else ""


def company_name_from_domain(url: str) -> str:
    """
    Infer a normalized company name from the website domain.

    Priority
    --------
    1. DOMAIN_NAME_OVERRIDES  (ibm → IBM, tcs → TCS, …)
    2. Domain-token capitalisation  (rockwell → Rockwell)

    Platform domains always return empty string — they are directories,
    not companies themselves.
    """
    if _is_platform_domain(url):
        return ""
    token = _domain_token(url)
    if not token:
        return ""
    if token in DOMAIN_NAME_OVERRIDES:
        return DOMAIN_NAME_OVERRIDES[token]
    words = re.split(r"[-_]+", token)
    return " ".join(word.capitalize() for word in words if word)


def company_name_from_platform_profile(url: str) -> str:
    """Extract and format company name from directory profile URL paths."""
    from discovery.directory_extractor import _PROFILE_PATTERNS
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    path = parsed.path.lower().strip("/")
    
    for domain_part, profile_prefix in _PROFILE_PATTERNS:
        prefix_clean = profile_prefix.strip("/")
        if domain_part in domain and prefix_clean in path:
            parts = [p for p in path.split("/") if p]
            prefix_parts = [p for p in prefix_clean.split("/") if p]
            if len(parts) > len(prefix_parts):
                token = parts[len(prefix_parts)]
                words = re.split(r"[-_]+", token)
                return " ".join(word.capitalize() for word in words if word)
    return ""


def _is_non_company_domain(url: str) -> bool:
    """Return True for known educational/media/reference/tutorial domains (Task 6)."""
    if not url:
        return True
    token = _domain_token(url)
    if not token:
        return True
    
    parsed = urlparse(url.lower())
    domain = parsed.netloc
    if domain.startswith("www."):
        domain = domain[4:]
        
    if domain in NON_COMPANY_DOMAINS or token in NON_COMPANY_DOMAINS:
        return True
        
    domain_parts = domain.split(".")
    tlds = {"com", "org", "net", "edu", "gov", "co", "in", "io", "tech", "ai", "app", "info", "biz"}
    for part in domain_parts:
        if part not in tlds and part in NON_COMPANY_DOMAINS:
            return True
            
    return False


def is_rejected_lead_domain(url: str) -> bool:
    """Return True when the domain belongs to a blocked non-lead website."""
    return _is_non_company_domain(url)


# ─────────────────────────────────────────────────────────────────────────────
# Quality penalty
# ─────────────────────────────────────────────────────────────────────────────

def quality_penalty(company: dict) -> int:
    """
    Calculate a numeric quality penalty for a discovered company record.

    A high penalty means the record is almost certainly not a B2B/B2C lead.
    Penalties are additive; the maximum meaningful value is ~100.
    """
    text = " ".join(
        str(company.get(key) or "")
        for key in ("company", "website", "source", "industry")
    ).lower()

    penalty = 0
    for term, points in QUALITY_PENALTIES.items():
        if term in text:
            penalty += points

    # Additional penalty when the domain itself is a known non-company site
    if is_rejected_lead_domain(company.get("website") or ""):
        penalty += 30

    return penalty


# ─────────────────────────────────────────────────────────────────────────────
# Result filtering
# ─────────────────────────────────────────────────────────────────────────────

def _url_path_contains_educational_signal(url: str) -> bool:
    """
    Return True when the URL path clearly belongs to an educational /
    informational sub-section of a site.
    """
    path = urlparse(url or "").path.lower()
    educational_path_signals = {
        "what-is-", "what_is_", "tutorial", "course", "learn",
        "guide", "blog", "news", "article", "definition",
        "ranking", "admission", "fees", "placement",
        "college", "university",
    }
    return any(signal in path for signal in educational_path_signals)


def _url_path_looks_like_company_profile(url: str) -> bool:
    """Return True when a platform URL points at a company profile, not a list page."""
    host = urlparse(url or "").netloc.lower()
    path = urlparse(url or "").path.lower().strip("/")
    if not path:
        return False

    full_path = f"/{path}"

    # Source-specific profile signatures are more accurate than generic path checks.
    if "clutch.co" in host and "/profile/" in full_path:
        return True
    if "goodfirms.co" in host and "/company/" in full_path:
        return True
    if "crunchbase.com" in host and "/organization/" in full_path:
        return True
    if "linkedin.com" in host and "/company/" in full_path:
        return True
    if "wellfound.com" in host and "/company/" in full_path:
        return True
    if "zoominfo.com" in host and "/c/" in full_path:
        return True

    company_signals = (
        "/company/",
        "/organization/",
        "/profile/",
        "/profiles/",
        "/business/",
        "/businesses/",
        "/c/",
    )
    return any(signal in full_path for signal in company_signals)


def _url_path_looks_like_listing(url: str) -> bool:
    """Return True when a URL points at a directory/listing/search page."""
    host = urlparse(url or "").netloc.lower()
    path = urlparse(url or "").path.lower().strip("/")
    if not path:
        return False

    full_path = f"/{path}"

    # Domain-aware listing signatures to avoid classifying company profiles as categories.
    if "clutch.co" in host and ("/search" in full_path or "/companies" in full_path):
        return True
    if "goodfirms.co" in host and ("/search" in full_path or "/directory" in full_path or "/companies" in full_path):
        return True
    if "crunchbase.com" in host and "/discover/" in full_path:
        return True

    listing_signals = (
        "/search",
        "/search/",
        "/directory",
        "/directories",
        "/category",
        "/categories",
        "/best",
        "/top",
        "/profiles",
    )
    return any(signal in full_path for signal in listing_signals)


def get_root_company_url(url: str) -> str:
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    if _is_platform_domain(url):
        return url
    return f"{parsed.scheme}://{parsed.netloc}"


def classify_page_type_with_confidence(url: str, title: str = "") -> tuple[str, float]:
    """
    Classify page kind into expanded taxonomy:
    - COMPANY_HOMEPAGE
    - COMPANY_PROFILE
    - DIRECTORY_LIST
    - MARKETPLACE
    - BLOG
    - ARTICLE
    - NEWS
    - SOCIAL
    - DOCUMENTATION
    - FORUM
    - JOB_POSTING
    - CAREERS
    - UNKNOWN

    Returns (page_type, confidence_score)
    """
    url = url or ""
    title = title or ""
    lowered_url = url.lower()
    lowered_title = title.lower()
    parsed = urlparse(lowered_url)
    domain = parsed.netloc
    path = parsed.path

    def is_platform():
        return any(platform in domain for platform in PLATFORM_DOMAINS)

    # 1. SOCIAL
    social_domains = {"linkedin.com", "facebook.com", "twitter.com", "x.com", "instagram.com", "youtube.com", "reddit.com", "pinterest.com"}
    if any(sd in domain for sd in social_domains):
        if "linkedin.com/company" in lowered_url:
            return "COMPANY_PROFILE", 0.98
        return "SOCIAL", 0.99

    # 2. COMPANY_PROFILE
    if "clutch.co/profile/" in lowered_url:
        return "COMPANY_PROFILE", 0.98
    if "goodfirms.co/company/" in lowered_url:
        return "COMPANY_PROFILE", 0.98
    if "crunchbase.com/organization/" in lowered_url:
        return "COMPANY_PROFILE", 0.98
    if "wellfound.com/company/" in lowered_url:
        return "COMPANY_PROFILE", 0.98
    if "zoominfo.com/c/" in lowered_url:
        return "COMPANY_PROFILE", 0.98
    if "apollo.io/companies/" in lowered_url:
        return "COMPANY_PROFILE", 0.98
    
    if "github.com/" in lowered_url:
        parts = [p for p in path.split("/") if p]
        if len(parts) == 1 and parts[0] not in {"features", "marketplace", "pricing", "trending", "explore", "topics", "collections", "login", "join", "search", "about"}:
            return "COMPANY_PROFILE", 0.95
        if len(parts) == 2 and parts[0] == "orgs":
            return "COMPANY_PROFILE", 0.95

    # 3. DIRECTORY_LIST
    if "clutch.co" in domain and ("/search" in path or "/companies" in path or "/directory" in path):
        return "DIRECTORY_LIST", 0.97
    if "goodfirms.co" in domain and ("/search" in path or "/directory" in path or "/companies" in path):
        return "DIRECTORY_LIST", 0.97
    if "crunchbase.com" in domain and "/discover/" in path:
        return "DIRECTORY_LIST", 0.97
    if _url_path_looks_like_listing(lowered_url):
        return "DIRECTORY_LIST", 0.95
    if any(term in lowered_title for term in ("top companies", "best companies", "top software", "best software", "directories", "directory list", "list of best")):
        return "DIRECTORY_LIST", 0.92

    # 4. MARKETPLACE
    if any(token in domain for token in ("play.google.com", "apps.apple.com", "chromewebstore.google.com")):
        return "MARKETPLACE", 0.99
    if "amazon.com" in domain or "ebay.com" in domain:
        return "MARKETPLACE", 0.95

    # 5. JOB_POSTING / CAREERS
    if "indeed.com" in domain or "glassdoor.com" in domain:
        if "job" in path or "viewjob" in lowered_url:
            return "JOB_POSTING", 0.95
        return "CAREERS", 0.90
    if "/job/" in path or "/jobs/" in path or "/careers/" in path or "/join-us" in path or "/careers-at/" in path:
        if re.search(r'\d+$', path) or "jobid" in lowered_url or "job_id" in lowered_url:
            return "JOB_POSTING", 0.90
        return "CAREERS", 0.95

    # 6. DOCUMENTATION
    if "docs." in domain or "/docs/" in path or "/documentation/" in path or "/api-reference/" in path:
        return "DOCUMENTATION", 0.92

    # 7. FORUM
    if any(fd in domain for fd in ("stackoverflow.com", "quora.com", "discourse", "reddit.com")) or "forum" in path or "forums" in path:
        return "FORUM", 0.95

    # 8. BLOG / ARTICLE / NEWS
    if "blog" in domain or "/blog" in path or "/blogs/" in path or "/post/" in path:
        return "BLOG", 0.95
    if "wikipedia.org" in domain:
        return "ARTICLE", 0.99
    if any(term in domain for term in ("techcrunch.com", "forbes.com", "nytimes.com", "bloomberg.com", "reuters.com", "medium.com")):
        return "NEWS", 0.95
    if _url_path_contains_educational_signal(lowered_url) or _title_contains_informational_term(lowered_title):
        if "news" in lowered_url or "press" in lowered_url:
            return "NEWS", 0.90
        if "blog" in lowered_url:
            return "BLOG", 0.90
        return "ARTICLE", 0.90

    # 9. COMPANY_HOMEPAGE
    if not is_platform() and not _is_non_company_domain(lowered_url):
        if path in {"", "/", "/index.html", "/index.php", "/home"}:
            return "COMPANY_HOMEPAGE", 0.90

    return "UNKNOWN", 0.40


def classify_company_page(url: str, title: str = "") -> str:
    """Classify a candidate page before final validation."""
    if url:
        url = get_root_company_url(url)
    page_type, _ = classify_page_type_with_confidence(url, title)
    if page_type == "COMPANY_HOMEPAGE":
        return "DIRECT_COMPANY"
    elif page_type == "COMPANY_PROFILE":
        return "DIRECTORY_COMPANY"
    elif page_type == "DIRECTORY_LIST":
        return "DIRECTORY_LIST"
    elif page_type in {"BLOG", "ARTICLE", "NEWS"}:
        lowered_url = (url or "").lower()
        if "blog" in lowered_url or "news" in lowered_url:
            return "BLOG"
        return "ARTICLE"
    elif page_type == "CAREERS":
        return "CATEGORY"
    
    # If the page type is UNKNOWN, verify if it is a private company page
    if url and not _is_platform_domain(url) and not _is_non_company_domain(url):
        return "DIRECT_COMPANY"
        
    return "CATEGORY"


def classify_result(result: dict) -> tuple[str, str | None]:
    """Classify search result into ALLOW, LIKELY_COMPANY, UNKNOWN, REJECT, DIRECTORY_LIST."""
    url = (result.get("url") or "").lower()
    title = (result.get("title") or "").lower()
    
    if not url:
        return "REJECT", "INVALID_URL"

    page_type, conf = classify_page_type_with_confidence(url, title)

    if conf >= 0.8:
        if page_type == "COMPANY_HOMEPAGE":
            return "ALLOW", "COMPANY_HOMEPAGE"
        if page_type == "COMPANY_PROFILE":
            return "ALLOW", "COMPANY_PROFILE"
        if page_type == "DIRECTORY_LIST":
            return "DIRECTORY_LIST", "DIRECTORY_LIST"
        if page_type in {"CAREERS", "JOB_POSTING"} and not _is_platform_domain(url) and not _is_non_company_domain(url):
            return "ALLOW", "CAREERS_HOMEPAGE_REDIRECT"
        return "REJECT", f"HIGH_CONF_{page_type}"

    return "UNKNOWN", "AMBIGUOUS"


def should_ignore_result(result: dict) -> bool:
    """Filter search results based on the new classification categories."""
    url = result.get("url", "")
    if "crunchbase.com" in url:
        return True
        
    classification, reason = classify_result(result)
    
    if classification in {"ALLOW", "LIKELY_COMPANY", "UNKNOWN", "DIRECTORY_LIST"}:
        result["classification"] = classification
        if DEBUG:
            print(f"[Discovery] Candidate: {result.get('url')} | Category: {classification} ({reason})")
        return False
        
    if DEBUG:
        print(f"[Discovery] Rejected: {result.get('url')} | Category: {classification} ({reason})")
    return True


def evaluate_direct_homepage(homepage_url: str, title: str, snippet: str, query_or_keyword: str, provider: str, ranker) -> dict | None:
    from discovery.homepage_evaluator import _fetch_homepage
    html = _fetch_homepage(homepage_url)
    if html:
        from query.expansion import record_query_outcome
        record_query_outcome(query_or_keyword, "homepage_crawled", provider=provider)
        sre_res = ranker.score_snippet(title, snippet, query_or_keyword, url=homepage_url)
        sre_res = ranker.score_html(html, query_or_keyword, sre_res, url=homepage_url)
        if sre_res["score"] >= config.RELEVANCE_THRESHOLD_LOW:
            return {
                "url": homepage_url,
                "relevance_score": sre_res["score"],
                "relevance_tier": sre_res["tier"],
                "relevance_info": sre_res
            }
    return None


def score_html_content(html: str, url: str, title: str, snippet: str, query_or_keyword: str, provider: str, ranker) -> dict | None:
    from query.expansion import record_query_outcome
    record_query_outcome(query_or_keyword, "homepage_crawled", provider=provider)
    sre_res = ranker.score_snippet(title, snippet, query_or_keyword, url=url)
    sre_res = ranker.score_html(html, query_or_keyword, sre_res, url=url)
    if sre_res["score"] >= config.RELEVANCE_THRESHOLD_LOW:
        return {
            "url": url,
            "relevance_score": sre_res["score"],
            "relevance_tier": sre_res["tier"],
            "relevance_info": sre_res
        }
    return None


def evaluate_url(url: str, title: str, snippet: str, query_or_keyword: str, provider: str) -> dict | None:
    from discovery.semantic_ranking_engine import SemanticRanker
    ranker = SemanticRanker()

    page_type, page_conf = classify_page_type_with_confidence(url, title)

    # 1. CAREERS / JOB_POSTING -> Root Homepage redirection
    if page_type in {"CAREERS", "JOB_POSTING"} and not _is_platform_domain(url) and not _is_non_company_domain(url):
        root_url = get_root_company_url(url)
        if root_url and root_url != url:
            url = root_url
            page_type = "COMPANY_HOMEPAGE"
            page_conf = 0.90

    # 2. Early rejection gate for high confidence non-company pages
    if page_conf >= 0.8 and page_type in {"ARTICLE", "BLOG", "NEWS", "SOCIAL", "DOCUMENTATION", "FORUM", "MARKETPLACE", "JOB_POSTING", "CAREERS"}:
        from utils.stats_tracker import record_rejection
        record_rejection(f"page_type_{page_type.lower()}")
        print(f"[REJECTED] URL: {url} | Title: {title!r} | Reason: High-confidence non-company page type ({page_type})")
        return None

    # 3. COMPANY_PROFILE -> Homepage Extraction & Evaluation with profile fallback
    if page_type == "COMPANY_PROFILE":
        from discovery.homepage_evaluator import _fetch_homepage
        profile_html = _fetch_homepage(url)
        if profile_html:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(profile_html, "html.parser")
            homepage_url, _ = ranker.extractor._extract_website(soup, profile_html, url)
            if homepage_url and homepage_url.strip() and not _is_platform_domain(homepage_url):
                homepage_res = evaluate_direct_homepage(homepage_url, title, snippet, query_or_keyword, provider, ranker)
                if homepage_res:
                    return homepage_res
            profile_res = score_html_content(profile_html, url, title, snippet, query_or_keyword, provider, ranker)
            if profile_res:
                return profile_res

    # 4. DIRECT_COMPANY / COMPANY_HOMEPAGE / or general page type
    sre_res = ranker.score_snippet(title, snippet, query_or_keyword, url=url)
    relevance_score = sre_res["score"]
    tier = sre_res["tier"]

    if relevance_score >= config.RELEVANCE_THRESHOLD_HIGH:
        from semantic.semantic_cache import get_cached_company
        cached_profile = get_cached_company(url)
        if cached_profile:
            sre_res["website"] = cached_profile.website
            sre_res["website_source"] = cached_profile.website_source
            sre_res["industry"] = ranker.detect_industry(
                cached_profile.sections.get("homepage", "") + " " + cached_profile.description.get("value", "")
            )
            return {
                "url": url,
                "relevance_score": relevance_score,
                "relevance_tier": "HIGH",
                "relevance_info": sre_res
            }
        else:
            from discovery.homepage_evaluator import _fetch_homepage
            html = _fetch_homepage(url)
            if html:
                from query.expansion import record_query_outcome
                record_query_outcome(query_or_keyword, "homepage_crawled", provider=provider)
                html_sre = ranker.score_html(html, query_or_keyword, sre_res, url=url)
                # Use the higher of the two scores — homepage text may be sparse
                # even for a real company (single-page apps, minimal copy, etc.)
                if html_sre["score"] >= sre_res["score"]:
                    sre_res = html_sre
                else:
                    print(f"[company_discovery] Homepage scored lower than snippet ({html_sre['score']} vs {relevance_score}); keeping directory score.")
                if sre_res["score"] >= config.RELEVANCE_THRESHOLD_LOW:
                    return {
                        "url": url,
                        "relevance_score": sre_res["score"],
                        "relevance_tier": sre_res["tier"],
                        "relevance_info": sre_res
                    }
                # Still below threshold even with directory score preserved — return directory result
                return {
                    "url": url,
                    "relevance_score": relevance_score,
                    "relevance_tier": "HIGH",
                    "relevance_info": sre_res
                }
            else:
                # Homepage blocked / non-HTML — trust the directory score
                return {
                    "url": url,
                    "relevance_score": relevance_score,
                    "relevance_tier": "HIGH",
                    "relevance_info": sre_res
                }
    elif relevance_score >= config.RELEVANCE_THRESHOLD_LOW:
        from discovery.homepage_evaluator import _fetch_homepage
        html = _fetch_homepage(url)
        if html:
            from query.expansion import record_query_outcome
            record_query_outcome(query_or_keyword, "homepage_crawled", provider=provider)
            html_sre = ranker.score_html(html, query_or_keyword, sre_res, url=url)
            # Use higher of homepage vs directory score
            if html_sre["score"] >= sre_res["score"]:
                sre_res = html_sre
            else:
                print(f"[company_discovery] Homepage scored lower than snippet ({html_sre['score']} vs {relevance_score}); keeping directory score.")
            if sre_res["score"] >= config.RELEVANCE_THRESHOLD_LOW:
                return {
                    "url": url,
                    "relevance_score": sre_res["score"],
                    "relevance_tier": sre_res["tier"],
                    "relevance_info": sre_res
                }
        else:
            # Homepage blocked / non-HTML — trust the directory score
            return {
                "url": url,
                "relevance_score": relevance_score,
                "relevance_tier": tier,
                "relevance_info": sre_res
            }
    else:
        from utils.stats_tracker import record_rejection
        record_rejection("semantic_low_score")

    return None


def validate_company_record(company: dict) -> tuple:
    """
    Final validation of a discovered company record before lead-card creation.

    Returns (True, None) for valid records.
    Returns (False, reason_str) for rejected records.
    """
    name = company.get("company") or ""
    website = company.get("website") or ""
    source_url = company.get("source_url") or ""
    linkedin = company.get("linkedin") or ""
    candidate_url = website or source_url or linkedin

    if not name:
        return False, "missing company name"

    if len(name) < 2:
        return False, "company name too short"

    if _title_contains_informational_term(name):
        return False, "company name looks informational"

    page_kind = classify_company_page(candidate_url, name)
    if page_kind in {"ARTICLE", "BLOG", "CATEGORY", "DIRECTORY_LIST"}:
        return False, f"{page_kind.lower()} page rejected"

    # Reject government and forum URLs
    if candidate_url and not is_lead_url_valid(candidate_url):
        return False, "government or forum URL rejected"

    # Direct websites must use a known business TLD
    if (
        website
        and not _is_platform_domain(website)
        and _domain_suffix(website) not in BUSINESS_DOMAIN_SUFFIXES
    ):
        return False, "unsupported website domain suffix"

    return True, None


# ─────────────────────────────────────────────────────────────────────────────
# Company name extraction
# ─────────────────────────────────────────────────────────────────────────────

def detect_source(url: str) -> str:
    """Map a result URL to its source label."""
    domain = urlparse(url).netloc.lower()
    for key, value in SOURCE_DOMAIN_MAP.items():
        if key in domain:
            return value
    return "Google"


def _candidate_matches_domain(candidate: str, domain_name: str) -> bool:
    norm_candidate = re.sub(r"[^a-z0-9]", "", (candidate or "").lower())
    norm_domain = re.sub(r"[^a-z0-9]", "", (domain_name or "").lower())
    return bool(norm_candidate and norm_candidate == norm_domain)


def _is_sentence_fragment(text: str) -> bool:
    """
    Return True only when the text looks like an informational phrase rather than a company name.
    Rejects strings starting with starter words, containing question marks, or carrying informational terms.
    """
    lowered = text.lower()
    sentence_starters = (
        "what ", "how ", "why ", "when ", "where ", "which ",
        "top ", "best ", "is ", "are ", "the ", "a ",
    )
    if any(lowered.startswith(s) for s in sentence_starters) or "?" in text:
        return True
    
    informational_indicators = (
        "tutorial", "guide", "definition", "vs", "versus", "comparison",
        "meaning", "overview", "documentation", "reference"
    )
    if any(ind in lowered for ind in informational_indicators):
        return True
    
    return False


def guess_company_name(result: dict) -> str:
    """
    Infer the best company name from title candidates and domain evidence.

    Priority (domain-first approach)
    ---------------------------------
    1. Hard domain override (ibm → IBM)
    2. Title candidate matches domain token
    3. Informational title → fall back to domain
    4. Business-signal candidates → prefer domain when available
    5. Last non-fragment candidate
    6. Domain name fallback
    """
    title = (result.get("title") or "").strip()
    url = result.get("url") or ""

    domain_name = company_name_from_domain(url)
    if not domain_name and _is_platform_domain(url):
        domain_name = company_name_from_platform_profile(url)
        
    domain_token = _domain_token(url)

    # 1. Hard override
    if domain_token in DOMAIN_NAME_OVERRIDES:
        return DOMAIN_NAME_OVERRIDES[domain_token]

    if not title:
        return domain_name

    # 2. Split title into candidates, strip platform noise
    candidates = _split_title_candidates(title)
    candidates = [c for c in candidates if c.lower() not in TITLE_NOISE_PARTS]

    title_is_informational = _title_contains_informational_term(title)

    # 3. Check whether any candidate matches the domain token
    if domain_name:
        for candidate in candidates:
            if _candidate_matches_domain(candidate, domain_name):
                return domain_name

        # Title is informational → trust domain over title
        if title_is_informational:
            return domain_name

    # 4. Prefer business-hint candidates
    business_candidates = [
        c for c in candidates
        if any(hint in c.lower() for hint in BUSINESS_HINTS)
    ]
    if business_candidates:
        return domain_name if domain_name else business_candidates[0]

    from utils.validators import is_valid_company_name
    
    # 5. Use the last non-fragment candidate (typically the site name)
    non_fragment_candidates = [c for c in candidates if not _is_sentence_fragment(c)]
    guessed_name = domain_name
    if len(non_fragment_candidates) > 1:
        guessed_name = non_fragment_candidates[-1]
    elif non_fragment_candidates:
        guessed_name = non_fragment_candidates[0]

    # Validate against noise words like "About Us"
    if not is_valid_company_name(guessed_name):
        return domain_name
        
    return guessed_name


def interleave_urls_by_domain(candidate_tuples: list) -> list:
    """Interleave tuples of (url, dir_title, dir_family) by the domain of the url.
    Allows round-robin scheduling across directory domains.
    """
    from urllib.parse import urlparse
    from collections import defaultdict
    domain_map = defaultdict(list)
    for tup in candidate_tuples:
        url = tup[0]
        domain = urlparse(url).netloc.lower()
        domain_map[domain].append(tup)
    
    interleaved = []
    # Round-robin retrieval
    while any(domain_map.values()):
        for domain in list(domain_map.keys()):
            if domain_map[domain]:
                interleaved.append(domain_map[domain].pop(0))
    return interleaved


# ─────────────────────────────────────────────────────────────────────────────
# Main discovery function  (Tasks 2, 4, 5, 11, 12)
# ─────────────────────────────────────────────────────────────────────────────

def discover_companies(keyword: str) -> list:
    """
    Run paginated search across all tasks for a keyword, qualify companies,
    and return a validated, normalized, deduplicated list of company dicts.

    Steps
    -----
    1. Generate search tasks from keyword.
    2. For each page (up to MAX_SEARCH_PAGES):
         a. Run every search task at the given page offset.
         b. Filter raw results (should_ignore_result).
         c. Extract company name + metadata.
         d. When the same company appears from multiple sources, keep the
            higher-confidence record (source_ranker.best_company_record).
         e. Stop early if TARGET_COMPANIES already collected.
    3. Apply quality_penalty → hard-reject high-penalty records.
    4. Validate each company record.
    5. Normalize company names (merge IBM India / IBM Corp → IBM).
    6. Deduplicate by normalised name.
    7. Update stats_tracker throughout.
    """
    # ── Priority Queue Scheduler Integration ──────────────────────────────────
    from network_client_project.network.scheduler import Scheduler
    from network_client_project.network.middleware.base import Request
    task_iterator = generate_search_tasks(keyword)

    from search.manager import get_search_manager
    manager = get_search_manager()
    manager.reset_keyword_state()

    scheduler = Scheduler()
    
    # Adaptive Source Priorities
    source_priorities = {
        "linkedin": 100,
        "clutch": 80,
        "goodfirms": 80,
        "crunchbase": 80,
        "wellfound": 80,
        "apollo": 80,
        "zoominfo": 80,
        "justdial": 50,
        "google": 20,
    }

    # Helper to enqueue next batch
    def enqueue_next_batch(batch_size=5):
        enqueued_count = 0
        for _ in range(batch_size):
            try:
                t = next(task_iterator)
                req = Request(
                    url="search",
                    query=t.query,
                    provider=t.source,
                    priority=source_priorities.get(t.source, 20),
                    meta={"page": 0, "max_results": 10, "source": t.source, "depth": 1}
                )
                scheduler.enqueue(req)
                stats.increment("queries_generated")
                enqueued_count += 1
            except StopIteration:
                break
        return enqueued_count

    # Seed the scheduler with initial search tasks (page 0)
    enqueue_next_batch(5)

    # key → company dict (dedup by company name during accumulation)
    accumulator: dict[str, dict] = {}
    directory_urls_to_mine = []
    mined_directory_urls = set()
    processed_company_urls = set()
    consecutive_zero_queries = 0
    family_zeroes: dict[str, int] = defaultdict(int)
    homepage_evals = 0
    
    unique_sources: set[str] = set()
    queries_since_new_source = 0
    
    # Rolling queue of last 8 query yields
    from collections import deque
    recent_yields = deque(maxlen=8)
    
    # Time limits and target thresholds
    discovery_start_time = time.time()
    last_accepted_time = time.time()
    
    # Configurable limits
    target_companies = getattr(config, "TARGET_COMPANIES", 50)
    target_high_confidence = getattr(config, "TARGET_HIGH_CONFIDENCE", 10)
    max_runtime = getattr(config, "MAX_RUNTIME", 30)
    
    # Dynamic timeout formula: base + 2s * active providers + 1s * active template families
    active_providers = sum(1 for pname in manager._priority if manager.provider_health.get(pname, False))
    from query.company_template import COMPANY_TEMPLATES
    active_families = len(COMPANY_TEMPLATES)
    timeout_cap = min(float(max_runtime), 20.0 + 2.0 * active_providers + 1.0 * active_families)
    
    from utils.deadline import Deadline
    Deadline.set_timeout(timeout_cap)
    if hasattr(manager, "_client") and hasattr(manager._client, "proxy_manager"):
        manager._client.proxy_manager.is_crawling = True
    
    exit_reason = "All enqueued tasks completed"

    while not scheduler.is_empty():
        req = scheduler.next()
        if not req:
            break

        pname = req.provider
        page = req.meta.get("page", 0)
        max_results = req.meta.get("max_results", 10)
        page_offset = page * max_results

        family = req.meta.get("source", "unknown")
        
        # Check provider exhaustion for this keyword + family
        if not manager.providers_available_for_keyword(family):
            print(f"[company_discovery] Skipping query '{req.query}' (No available providers for family '{family}')")
            if scheduler.is_empty():
                enqueue_next_batch(5)
            continue
            
        if family_zeroes[family] >= 3:
            print(f"[company_discovery] Skipping query '{req.query}' (Family '{family}' exhausted)")
            if scheduler.is_empty():
                enqueue_next_batch(5)
            continue

        task_yielded = False
        start_time = time.time()
        accepted_count_total = 0
        rejected_count_total = 0
        parsed_count_total = 0
        provider_name = pname
        sources_before = len(unique_sources)

        stats.increment("funnel_requests_sent")

        try:
            # Execute search
            raw_results = run_search(req.query, start=page_offset, family=family)
            from search.manager import get_search_manager
            manager = get_search_manager()
            is_cache_served = manager.last_provider_used == "cache"

            if is_cache_served:
                stats.increment("cache_served_queries")
            else:
                stats.increment("funnel_http_success")

        except Exception as e:
            print(f"[company_discovery] search failed for query '{req.query}': {e}")
            # Adaptive priority feedback loop: decrease on failure
            source_priorities[family] = max(10, source_priorities.get(family, 50) - 20)
            scheduler.update_priorities(source_priorities)
            raw_results = []
        
        stats.increment("queries_executed")
        stats.increment("search_results", len(raw_results))

        parsed_count_total += len(raw_results)

        accepted_count = 0
        for result in raw_results:
            url = result.get("url")
            if not url:
                rejected_count_total += 1
                continue

            stats.increment("funnel_business_candidates")

            if should_ignore_result(result):
                stats.increment("rejected_results")
                rejected_count_total += 1
                classification, reason = classify_result(result)
                print(f"[REJECTED] URL: {url} | Title: {result.get('title')!r} | Snippet: {result.get('snippet')!r} | Reason: Page classification is {classification} ({reason})")
                continue

            # Route DIRECTORY_LIST results to the secondary mining queue
            if result.get("classification") == "DIRECTORY_LIST":
                directory_urls_to_mine.append((url, result.get("title", ""), family))
                stats.increment("directory_queued")
                if DEBUG:
                    print(f"[Discovery] Queued directory for mining: {url}")
                continue

            from discovery.semantic_ranking_engine import SemanticRanker
            ranker = SemanticRanker()

            # Step 1: Snippet-level scoring
            sre_res = ranker.score_snippet(result.get("title", ""), result.get("snippet", ""), keyword)
            relevance_score = sre_res["score"]
            tier = sre_res["tier"]

            # Two-stage checks
            if relevance_score >= config.RELEVANCE_THRESHOLD_HIGH:
                # Accept immediately, no homepage crawl needed
                result["classification"] = "ALLOW"
                result["relevance_score"] = relevance_score
                result["relevance_tier"] = "HIGH"
                result["relevance_info"] = sre_res
            elif relevance_score < config.RELEVANCE_THRESHOLD_LOW:
                # Reject immediately, snippet has low relevance
                stats.increment("rejected_results")
                rejected_count_total += 1
                print(f"[REJECTED] URL: {url} | Title: {result.get('title')!r} | Snippet: {result.get('snippet')!r} | Reason: Low snippet relevance score {relevance_score} (< {config.RELEVANCE_THRESHOLD_LOW})")
                continue
            else:
                # Ambiguous/borderline snippet, perform HTML deep scoring
                if homepage_evals < 10:
                    homepage_evals += 1
                    
                    from discovery.homepage_evaluator import _fetch_homepage
                    html = _fetch_homepage(url)
                    
                    if html:
                        # Full HTML score
                        sre_res = ranker.score_html(html, keyword, sre_res)
                        relevance_score = sre_res["score"]
                        tier = sre_res["tier"]
                        
                        if relevance_score < config.RELEVANCE_THRESHOLD_LOW:
                            stats.increment("rejected_results")
                            rejected_count_total += 1
                            print(f"[REJECTED] URL: {url} | Title: {result.get('title')!r} | Snippet: {result.get('snippet')!r} | Reason: Low HTML relevance score {relevance_score} (< {config.RELEVANCE_THRESHOLD_LOW})")
                            continue
                            
                        # Reclassify based on relevance
                        result["classification"] = "ALLOW" if relevance_score >= config.RELEVANCE_THRESHOLD_HIGH else "LIKELY_COMPANY"
                        result["relevance_score"] = relevance_score
                        result["relevance_tier"] = tier
                        result["relevance_info"] = sre_res
                        
                        # Set detected industry
                        if sre_res.get("industry") != "Unknown":
                            result["industry_detected"] = sre_res["industry"]
                            
                        stats.increment("homepage_success")
                        from stats.provider_stats import provider_stats
                        provider_stats.record_homepage_success(pname)
                    else:
                        # If fetch failed, fallback to snippet score or reject
                        if relevance_score < config.RELEVANCE_THRESHOLD_LOW:
                            stats.increment("rejected_results")
                            rejected_count_total += 1
                            print(f"[REJECTED] URL: {url} | Title: {result.get('title')!r} | Snippet: {result.get('snippet')!r} | Reason: Low fallback snippet relevance score {relevance_score} (< {config.RELEVANCE_THRESHOLD_LOW}) after HTML fetch failed")
                            continue
                        result["classification"] = "LIKELY_COMPANY"
                        result["relevance_score"] = relevance_score
                        result["relevance_tier"] = tier
                        result["relevance_info"] = sre_res
                else:
                    # Budget exhausted, use snippet score
                    if relevance_score < config.RELEVANCE_THRESHOLD_LOW:
                        stats.increment("rejected_results")
                        rejected_count_total += 1
                        print(f"[REJECTED] URL: {url} | Title: {result.get('title')!r} | Snippet: {result.get('snippet')!r} | Reason: Low budget-exhausted snippet relevance score {relevance_score} (< {config.RELEVANCE_THRESHOLD_LOW})")
                        continue
                    result["classification"] = "LIKELY_COMPANY"
                    result["relevance_score"] = relevance_score
                    result["relevance_tier"] = tier
                    result["relevance_info"] = sre_res

            company_name = guess_company_name(result)
            if not company_name:
                rejected_count_total += 1
                print(f"[REJECTED] URL: {url} | Title: {result.get('title')!r} | Snippet: {result.get('snippet')!r} | Reason: Could not guess company name")
                continue

            print(f"[SRE Debug] Company: {company_name} | Score: {relevance_score} | Tier: {tier} | Industry: {sre_res.get('industry')} | Matched: {sre_res.get('matched_signals')}")

            stats.increment("funnel_business_accepted")
            accepted_count_total += 1
            accepted_count += 1
            key = company_name.lower()
            source = detect_source(url)

            new_record = {
                "company": company_name,
                "website": None,
                "linkedin": None,
                "source_url": url,
                "industry": keyword,
                "location": None,
                "source": source,
                "classification": result.get("classification", "UNKNOWN"),
                "relevance_score": relevance_score,
                "relevance_tier": tier,
                "relevance_info": sre_res,
                "industry_detected": sre_res.get("industry", "Unknown"),
            }

            # Attach URL to the right slot
            if "linkedin.com" in url:
                new_record["linkedin"] = url
            elif not _is_platform_domain(url):
                new_record["website"] = url

            if key not in accumulator:
                accumulator[key] = new_record
                unique_sources.add(source)
            else:
                stats.increment("duplicate_companies")
                accumulator[key] = best_company_record(
                    accumulator[key], new_record
                )
                unique_sources.add(accumulator[key]["source"])
        
        # Enqueue next page if pagination is supported and current page yielded results
        if raw_results and page + 1 < config.MAX_SEARCH_PAGES:
            next_req = Request(
                url="search",
                query=req.query,
                provider=pname,
                priority=source_priorities.get(pname, 20),
                meta={"page": page + 1, "max_results": max_results, "source": pname, "depth": 1}
            )
            scheduler.enqueue(next_req)

        # Update dynamic priorities based on yield
        if accepted_count > 0:
            task_yielded = True
            # Online multi-armed bandit reward: increase priority based on yield
            source_priorities[family] = min(150, source_priorities.get(family, 50) + 10 * accepted_count)
            scheduler.update_priorities(source_priorities)
            last_accepted_time = time.time()
        else:
            # Online multi-armed bandit penalty: decrease priority
            source_priorities[family] = max(10, source_priorities.get(family, 50) - 20)
            scheduler.update_priorities(source_priorities)
            
        recent_yields.append(accepted_count)
            
        time_taken = time.time() - start_time
        print(f"[Discovery Stats] Source: {provider_name:<20} | Query: '{req.query}' | Parsed: {parsed_count_total} | Accepted: {accepted_count_total} | Rejected: {rejected_count_total} | Time: {time_taken:.2f}s")
        
        if task_yielded:
            consecutive_zero_queries = 0
            family_zeroes[family] = 0
            if len(unique_sources) > sources_before:
                queries_since_new_source = 0
            else:
                queries_since_new_source += 1
        else:
            consecutive_zero_queries += 1
            family_zeroes[family] += 1
            
        if consecutive_zero_queries >= 6:
            print("[company_discovery] Stopping: Last 6 queries yielded 0 companies (Providers exhausted/blocked).")
            exit_reason = "6 consecutive zero-result queries"
            break
            
        if queries_since_new_source >= 6:
            print("[company_discovery] Stopping: Source diversity stagnated (no new sources in 6 yielding queries).")
            exit_reason = "Source diversity stagnated"
            break

        # ROI check: if we've run enough queries but yielding <15%, stop
        queries_run = stats.get().get("queries_executed", 0)
        if queries_run >= 8:
            yield_rate = len(accumulator) / queries_run
            if yield_rate < 0.15:
                print(f"[company_discovery] Stopping: ROI too low (Yield: {yield_rate:.1%}, Companies: {len(accumulator)}, Queries: {queries_run}).")
                exit_reason = "ROI too low"
                break

        # Check total run time (dynamic cap)
        elapsed = time.time() - discovery_start_time
        if elapsed >= timeout_cap:
            print(f"[company_discovery] Stopping: Maximum adaptive runtime cap ({timeout_cap:.1f}s) exceeded (Elapsed: {elapsed:.1f}s).")
            exit_reason = "Adaptive runtime cap exceeded"
            break

        # Check productivity (no new accepted companies for 10 consecutive seconds)
        if (time.time() - last_accepted_time >= 10.0) and len(accumulator) > 0:
            print("[company_discovery] Stopping: No new accepted companies for 10 consecutive seconds.")
            exit_reason = "No new accepted companies for 10s"
            break

        # Check rolling query yields (no accepted companies in last 8 queries)
        if len(recent_yields) >= 8 and sum(recent_yields) == 0:
            print("[company_discovery] Stopping: No accepted companies from the last 8 executed queries.")
            exit_reason = "Last 8 queries yielded 0 results"
            break

        # Early exit when target reached
        high_confidence_count = sum(1 for c in accumulator.values() if c.get("classification") == "ALLOW")
        if len(accumulator) >= target_companies:
            print(f"[company_discovery] Stopping: Target companies limit ({target_companies}) reached.")
            exit_reason = f"Target companies ({target_companies}) reached"
            break
        if high_confidence_count >= target_high_confidence:
            print(f"[company_discovery] Stopping: Target high-confidence companies ({target_high_confidence}) reached.")
            exit_reason = f"Target high confidence ({target_high_confidence}) reached"
            break
            
        # Refill batch if scheduler is empty
        if scheduler.is_empty():
            enqueue_next_batch(5)

    # ── Process Directory Queue (Secondary Queue) ──────────────────────────────
    if directory_urls_to_mine:
        print(f"\n[Discovery] Processing directory queue: {len(directory_urls_to_mine)} directories collected")
        from discovery.directory_extractor import extract_company_links
        from discovery.homepage_evaluator import _fetch_homepage
        import random
        
        all_candidate_profiles = []
        for dir_url, dir_title, dir_family in directory_urls_to_mine:
            print(f"[Discovery] Mining directory: {dir_url}")
            dir_html = _fetch_homepage(dir_url)
            if not dir_html:
                print(f"[Discovery] Failed to fetch directory page: {dir_url}")
                continue
                
            extracted_links = extract_company_links(dir_html, dir_url)
            print(f"[Discovery] Extracted {len(extracted_links)} links from directory {dir_url}")
            stats.increment("directory_mined", len(extracted_links))
            
            for ext_url in extracted_links:
                if ext_url not in processed_company_urls:
                    all_candidate_profiles.append((ext_url, dir_title, dir_family))
                    
        # Interleave candidates by domain
        interleaved_candidates = interleave_urls_by_domain(all_candidate_profiles)
        
        # Limit candidate evaluation queue to avoid hammering directories and blowing budget
        max_eval = getattr(config, "MAX_DIRECTORY_CANDIDATES_TO_EVALUATE", 50)
        candidates_to_process = interleaved_candidates[:max_eval]
        print(f"[Discovery] Interleaved {len(interleaved_candidates)} directory candidate profiles across domains.")
        print(f"[Discovery] Capping candidate processing queue at {len(candidates_to_process)} (Max allowed: {max_eval}).")
        
        # Concurrently evaluate candidate profiles in parallel to reduce sequential delay
        from concurrent.futures import ThreadPoolExecutor
        import threading
        
        num_workers = getattr(config, "DISCOVERY_PARALLEL_WORKERS", 5)
        print(f"\n[Discovery] Evaluating {len(candidates_to_process)} directory candidate profiles in parallel using {num_workers} workers...")
        
        eval_lock = threading.Lock()
        domain_last_time = {}
        domain_time_lock = threading.Lock()
        
        def evaluate_candidate(cand):
            ext_url, dir_title, dir_family = cand
            if "crunchbase.com" in ext_url:
                return None
            if ext_url in processed_company_urls:
                return None
                
            from urllib.parse import urlparse
            domain = urlparse(ext_url).netloc.lower().lstrip("www.")
            
            with domain_time_lock:
                last_time = domain_last_time.get(domain, 0.0)
                now = time.time()
                # Politeness delay of 3.0 seconds per domain to prevent concurrent WAF rate limits
                wait_needed = max(0.0, 3.0 - (now - last_time))
                domain_last_time[domain] = now + wait_needed
                
            if wait_needed > 0:
                time.sleep(wait_needed)
                
            try:
                # Evaluate company profile or direct URL
                eval_res = evaluate_url(ext_url, "", "", keyword, dir_family)
                if eval_res:
                    return (cand, eval_res)
            except Exception as e:
                print(f"[Discovery] Error evaluating candidate {ext_url}: {e}")
            return None

        # Execute thread pool
        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(evaluate_candidate, cand) for cand in candidates_to_process]
            
            for future in futures:
                res = future.result()
                if not res:
                    continue
                
                cand, eval_res = res
                ext_url, dir_title, dir_family = cand
                
                # Check again under lock to avoid race conditions
                with eval_lock:
                    if eval_res["url"] in processed_company_urls:
                        continue
                    processed_company_urls.add(eval_res["url"])
                
                # Guess company name
                result_mock = {"title": "", "snippet": "", "url": eval_res["url"]}
                company_name = guess_company_name(result_mock)
                if not company_name:
                    continue
                    
                sre_res = eval_res["relevance_info"]
                relevance_score = eval_res["relevance_score"]
                tier = eval_res["relevance_tier"]
                
                print(f"[SRE Directory Lead] Company: {company_name} | Score: {relevance_score} | Tier: {tier} | Industry: {sre_res.get('industry')}")
                
                stats.increment("funnel_business_accepted")
                
                # Lock modifications to shared stats, accumulator, and unique_sources
                with eval_lock:
                    accepted_count_total += 1
                    key = company_name.lower()
                    source = detect_source(eval_res["url"])
                    
                    new_record = {
                        "company": company_name,
                        "website": sre_res.get("website") or None,
                        "website_source": sre_res.get("website_source") or None,
                        "linkedin": None,
                        "source_url": eval_res["url"],
                        "industry": keyword,
                        "query": dir_title or keyword,
                        "location": None,
                        "source": source,
                        "classification": "UNKNOWN",
                        "relevance_score": relevance_score,
                        "relevance_tier": tier,
                        "relevance_info": sre_res,
                        "industry_detected": sre_res.get("industry", "Unknown"),
                    }

                    if "linkedin.com" in eval_res["url"]:
                        new_record["linkedin"] = eval_res["url"]
                    elif not _is_platform_domain(ext_url):
                        new_record["website"] = eval_res["url"]
                    
                    if key in accumulator:
                        accumulator[key] = best_company_record(accumulator[key], new_record)
                        unique_sources.add(accumulator[key]["source"])
                    else:
                        accumulator[key] = new_record
                        unique_sources.add(source)

    # ── Task Preservation ──────────────────────────────────────────────────
    remaining = []
    for _ in range(20):
        try:
            remaining.append(next(task_iterator).query)
        except StopIteration:
            break
            
    rest_count = 0
    for _ in task_iterator:
        rest_count += 1
        
    if remaining or rest_count > 0:
        import json
        os.makedirs("output", exist_ok=True)
        with open("output/remaining_tasks.json", "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "keyword": keyword,
                "reason": exit_reason,
                "remaining_count": len(remaining) + rest_count,
                "next_tasks": remaining
            }) + "\n")

    # ── Apply quality penalty + structural validation ─────────────────────
    validated = []
    for company in accumulator.values():
        penalty = quality_penalty(company)
        if penalty >= HARD_REJECT_PENALTY_THRESHOLD:
            stats.increment("rejected_results")
            print(
                f"[company_discovery] hard-rejected {company.get('company')!r}"
                f" (penalty={penalty})"
            )
            continue

        is_valid, reason = validate_company_record(company)
        if is_valid:
            stats.increment("validated_companies")
            stats.increment("funnel_leads")
            validated.append(company)
        else:
            stats.increment("rejected_results")
            print(
                f"[company_discovery] rejected {company.get('company')!r}"
                f": {reason}"
            )

    # ── Task 11: Normalize company names (merge variants) ─────────────────
    normalized = normalize_companies(validated)

    # Sort normalized descending by relevance score so dedupe_companies keeps the highest relevance candidate
    normalized.sort(key=lambda c: c.get("relevance_score", 0), reverse=True)

    # ── Deduplicate by normalised name ────────────────────────────────────
    result = dedupe_companies(normalized)
    stats.set_value("validated_companies", len(result))

    if hasattr(manager, "_client") and hasattr(manager._client, "proxy_manager"):
        manager._client.proxy_manager.is_crawling = False

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Manual test entry-point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    results = discover_companies("Software Companies Noida")
    print()
    print("=" * 60)
    print("Companies Found:", len(results))
    print("=" * 60)
    for c in results:
        print(c)
