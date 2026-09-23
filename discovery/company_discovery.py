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
from utils.deadline import Deadline
from concurrent.futures import ThreadPoolExecutor

DEBUG = os.getenv("DISCOVERY_DEBUG", "false").lower() == "true"

# Force UTF-8 output on Windows to prevent UnicodeEncodeError
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

_p1_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "pillar1"))
if _p1_path not in sys.path:
    sys.path.insert(0, _p1_path)

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
    website = company.get("website")
    if website and is_rejected_lead_domain(website):
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

    # F6S and other aggregators: any path with /companies/ is a listing
    aggregator_domains = {
        "f6s.com", "angel.co", "angellist.com", "wellfound.com",
        "dealroom.co", "tracxn.com", "producthunt.com", "growjo.com",
        "topstartups.io", "startupranking.com", "ventureradar.com",
        "cbinsights.com", "owler.com", "g2.com", "capterra.com",
        "getapp.com", "trustpilot.com",
    }
    if any(ag in host for ag in aggregator_domains):
        return True  # All pages on aggregators are listing/research pages, not company homepages

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
        "/companies/",     # Universal: any site's /companies/X path = listing
        "/startups/",      # Universal: /startups/X = listing
        "/lists/",
        "/rankings/",
        "/explore/",
        "/discover/",
        "/collection/",
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

    # Aggregator / VC directory platforms → always DIRECTORY_LIST
    _aggregator_domains = {
        "f6s.com", "angel.co", "angellist.com", "wellfound.com",
        "dealroom.co", "tracxn.com", "producthunt.com", "growjo.com",
        "topstartups.io", "startupranking.com", "eu-startups.com",
        "ventureradar.com", "cbinsights.com", "owler.com",
        "g2.com", "capterra.com", "getapp.com", "trustpilot.com",
    }
    if any(ag in domain for ag in _aggregator_domains):
        return "DIRECTORY_LIST", 0.97

    if _url_path_looks_like_listing(lowered_url):
        return "DIRECTORY_LIST", 0.95

    # Regex-based title matching for listicle / ranking page patterns
    _listing_title_re = re.compile(
        r'\b(top|best|leading|list of|top \d+|best \d+)\b.*\b(companies|startups|agencies|firms|tools|platforms|software|solutions)\b',
        re.IGNORECASE
    )
    if _listing_title_re.search(lowered_title):
        return "DIRECTORY_LIST", 0.92
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

    from extraction.page_extractor import is_disallowed_subpage_url
    if is_disallowed_subpage_url(url, result.get("title", "")):
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


def evaluate_direct_homepage(homepage_url: str, title: str, snippet: str, query_or_keyword: str, provider: str, ranker, deadline: Deadline | None = None) -> dict | None:
    from discovery.homepage_evaluator import _fetch_homepage
    html = _fetch_homepage(homepage_url, deadline=deadline)
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


def evaluate_url(url: str, title: str, snippet: str, query_or_keyword: str, provider: str, deadline: Deadline | None = None) -> dict | None:
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
        profile_html = _fetch_homepage(url, deadline=deadline)
        if profile_html:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(profile_html, "html.parser")
            homepage_url, _ = ranker.extractor._extract_website(soup, profile_html, url)
            if homepage_url and homepage_url.strip() and not _is_platform_domain(homepage_url):
                homepage_res = evaluate_direct_homepage(homepage_url, title, snippet, query_or_keyword, provider, ranker, deadline=deadline)
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
            html = _fetch_homepage(url, deadline=deadline)
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
        html = _fetch_homepage(url, deadline=deadline)
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

    industry_kw = company.get("industry") or ""
    if industry_kw:
        from query.intent_classifier import is_entity_query
        if is_query_as_company(name, industry_kw, not is_entity_query(industry_kw)):
            return False, "query as company name rejected"

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


def canonical_company_id(company: dict) -> str:
    """Return a stable identity key from domain, LinkedIn slug, or name."""
    website = company.get("website") or ""
    token = _domain_token(website)
    if token and not _is_platform_domain(website):
        return f"domain:{token}"
    linkedin = (company.get("linkedin") or "").lower()
    match = re.search(r"linkedin\.com/company/([^/?#]+)", linkedin)
    if match:
        return f"linkedin:{match.group(1).replace('-', '')}"
    name = re.sub(r"[^a-z0-9]", "", (company.get("company") or "").lower())
    return f"name:{name}" if name else ""


def minimum_evidence_gate(company: dict) -> tuple[bool, str | None]:
    """Reject candidates lacking identity, source URL, or relevance evidence."""
    if not (company.get("company") or "").strip():
        return False, "missing_company_identity"
    if not (company.get("website") or company.get("linkedin") or company.get("source_url")):
        return False, "missing_source_evidence"
    if float(company.get("relevance_score", 0) or 0) < config.RELEVANCE_THRESHOLD_LOW:
        return False, "below_relevance_threshold"
    return True, None


def company_intent_gate(company: dict, keyword: str) -> tuple[bool, str | None]:
    """Require company evidence in addition to topical relevance for categories."""
    name = (company.get("company") or "").strip()
    from query.intent_classifier import is_entity_query
    if is_query_as_company(name, keyword, not is_entity_query(keyword)):
        return False, "query_as_company_rejected"

    relevance = float(company.get("relevance_score", 0) or 0)
    has_official_domain = bool(company.get("website"))
    linkedin_url = company.get("linkedin") or ""
    has_linkedin = bool("linkedin.com/company" in linkedin_url.lower())
    industry = (company.get("industry_detected") or "").lower()
    info = company.get("relevance_info") or {}
    matched = [str(signal).lower() for signal in info.get("matched_signals", [])]
    category_terms = set(re.findall(r"[a-z0-9]+", keyword.lower()))
    category_signal = bool(
        category_terms.intersection(set(re.findall(r"[a-z0-9]+", industry)))
        or any(term in " ".join(matched) for term in category_terms if len(term) > 2)
    )
    company_evidence = 0
    if len(name.split()) >= 2 and len(name) >= 3:
        company_evidence += 1
    if company.get("description") or (isinstance(info, dict) and info.get("description")):
        company_evidence += 1
    if company.get("employees") or company.get("company_size"):
        company_evidence += 1
    if company.get("location") or company.get("country"):
        company_evidence += 1
    if company.get("industry_detected") and company.get("industry_detected") != "Unknown":
        company_evidence += 1

    if has_official_domain and relevance >= config.RELEVANCE_THRESHOLD_LOW:
        return True, None
    if has_linkedin and category_signal and company_evidence >= 2:
        return True, None
    if has_linkedin and not has_official_domain:
        if len(name.split()) < 2 or _title_contains_informational_term(name):
            return False, "topic_match_only_linkedin_without_official_domain"
        if company_evidence >= 1:
            return False, "linkedin_company_evidence_insufficient"
        return False, "topic_match_only_linkedin_without_official_domain"
    if not category_signal and not has_official_domain:
        return False, "company_identity_without_category_evidence"
    return False, "insufficient_company_intent_evidence"


def partial_lead_gate(company: dict, reason: str | None) -> tuple[bool, str | None]:
    """Retain useful incomplete company records without accepting topic pages."""
    if not reason:
        return True, None
    if reason in ("topic_match_only_linkedin_without_official_domain", "query_as_company_rejected"):
        return False, reason
    name = (company.get("company") or "").strip()
    linkedin_url = company.get("linkedin") or ""
    has_linkedin = bool("linkedin.com/company" in linkedin_url.lower())
    has_source = bool(company.get("source_url") or company.get("website") or company.get("linkedin"))
    informational = _title_contains_informational_term(name) or bool(
        re.search(r"^(top|best|list of|leading)\b|\bcompanies\s+(in|to|for)\b", name.lower())
    )
    if informational:
        return False, "informational_page_rejected"

    # Count company-level signals (industry, description, employees, location, title/name)
    info = company.get("relevance_info") or {}
    company_signals = 0
    if len(name.split()) >= 2 and len(name) >= 3:
        company_signals += 1
    if company.get("description") or (isinstance(info, dict) and info.get("description")):
        company_signals += 1
    if company.get("employees") or company.get("company_size"):
        company_signals += 1
    if company.get("location") or company.get("country"):
        company_signals += 1
    if company.get("industry_detected") and company.get("industry_detected") != "Unknown":
        company_signals += 1

    # Require LinkedIn company URL + identity + at least one company-level signal
    if has_linkedin and has_source and len(name) >= 2 and company_signals >= 1:
        return True, reason
    return False, reason


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
    if not norm_candidate or not norm_domain:
        return False
    return (
        norm_candidate == norm_domain
        or norm_domain in norm_candidate
        or norm_candidate.startswith(norm_domain)
    )


def is_query_as_company(company_name: str, query: str, is_category_query: bool) -> bool:
    """
    Contextually rejects candidates whose name is identical to the search category.
    Only active when query is a category query.
    Allows real companies with extra words (e.g., 'Electronics India Pvt Ltd', 'Havells Consumer Electronics').
    """
    if not is_category_query or not company_name or not query:
        return False
    norm_name = re.sub(r"[^a-z0-9]", "", str(company_name).lower())
    norm_query = re.sub(r"[^a-z0-9]", "", str(query).lower())
    return bool(norm_name and norm_query and norm_name == norm_query)


def _is_sentence_fragment(text: str) -> bool:
    """
    Return True only when the text looks like an informational phrase rather than a company name.
    Rejects strings starting with starter words, containing question marks, or carrying informational terms.
    """
    lowered = text.lower()
    sentence_starters = (
        "what ", "how ", "why ", "when ", "where ", "which ",
        "top ", "best ", "popular ", "list of ", "leading ",
        "is ", "are ", "the ", "a ",
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
    candidates = [c.strip() for c in candidates if c.strip() and c.lower().strip() not in TITLE_NOISE_PARTS]

    title_is_informational = _title_contains_informational_term(title)

    # 3. Check whether any candidate matches the domain token
    if domain_name:
        for candidate in candidates:
            if _candidate_matches_domain(candidate, domain_name):
                cand_clean = candidate.strip()
                if 1 <= len(cand_clean.split()) <= 4 and not _is_sentence_fragment(cand_clean):
                    return cand_clean
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
    
    # 5. Homepage vs subpage candidate preference
    non_fragment_candidates = [c for c in candidates if not _is_sentence_fragment(c)]
    guessed_name = domain_name
    if non_fragment_candidates:
        parsed = urlparse(url)
        path = (parsed.path or "").strip("/").lower()
        is_homepage = not path or path in ("in", "en", "us", "home", "index.html", "default.aspx")
        if is_homepage:
            guessed_name = non_fragment_candidates[0]
        elif len(non_fragment_candidates) > 1:
            guessed_name = non_fragment_candidates[-1]
        else:
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

from utils.deadline import Deadline, DeadlineExceeded


def discover_companies(keyword: str, deadline: "Deadline | None" = None) -> list:
    """
    Run paginated search across all tasks for a keyword, qualify companies,
    and return a validated, normalized, deduplicated list of company dicts.
    """
    from utils.deadline import Deadline
    if deadline and deadline.is_exceeded():
        print(f"[company_discovery] Deadline exceeded before discovery start.")
        return []

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
        "linkedin": 90,
        "clutch": 80,
        "goodfirms": 80,
        "crunchbase": 80,
        "wellfound": 80,
        "apollo": 80,
        "zoominfo": 80,
        "justdial": 50,
        "google": 70,
        "brave": 70,
        "duckduckgo": 70,
        "bing": 70,
    }

    # Helper to enqueue next batch
    def enqueue_next_batch(batch_size=5):
        enqueued_count = 0
        for _ in range(batch_size):
            try:
                t = next(task_iterator)
                is_direct = getattr(t, "discovery_mode", "expanded") == "direct"
                is_site_dork = "site:" in t.query.lower()
                
                # Direct web discovery (broad company queries without site: restrictions)
                # gets highest priority so it runs before/alongside LinkedIn
                if is_direct and not is_site_dork:
                    req_priority = 100
                elif is_direct and "linkedin" in t.query.lower():
                    req_priority = 90
                elif not is_site_dork:
                    req_priority = source_priorities.get(t.source, 70)
                else:
                    req_priority = source_priorities.get(t.source, 50)

                req = Request(
                    url="search",
                    query=t.query,
                    provider=t.source,
                    priority=req_priority,
                    meta={
                        "page": 0,
                        "max_results": 10,
                        "source": t.source,
                        "depth": 1,
                        "discovery_mode": getattr(t, "discovery_mode", "expanded"),
                        "original_keyword": getattr(t, "original_keyword", keyword),
                        "family": getattr(t, "family", "COMPANY"),
                        "operator_set": getattr(t, "operator_set", []),
                        "intent": getattr(t, "intent", "discovery"),
                        "expected_information": getattr(t, "expected_information", ""),
                    }
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
    # ``run_pipeline --target-leads`` is the user-facing cap.  Honour it in
    # category discovery as well, rather than continuing toward the legacy
    # TARGET_COMPANIES default after enough genuine leads were found.
    target_leads_limit = getattr(config, "TARGET_LEADS_LIMIT", 0)
    if target_leads_limit > 0:
        target_companies = min(target_companies, target_leads_limit)
    target_high_confidence = getattr(config, "TARGET_HIGH_CONFIDENCE", 10)
    serpapi_sufficient = False
    discovery_deadline = deadline if deadline else Deadline(getattr(config, "DISCOVERY_DEADLINE_SECONDS", 55.0))
    # search_deadline is a phase-bounded child: uses at most SEARCH_MAX_RUNTIME seconds
    # but is also capped by whatever discovery time remains — no independent clock.
    search_deadline = discovery_deadline.child(
        min(getattr(config, "SEARCH_MAX_RUNTIME", 45.0), discovery_deadline.remaining())
    )

    if hasattr(manager, "_client") and hasattr(manager._client, "proxy_manager"):
        manager._client.proxy_manager.is_crawling = True
    
    exit_reason = "All enqueued tasks completed"
    discovery_report = {
        "keyword": keyword,
        "providers": [],
        "candidates": [],
        "stages": {"DISCOVERED": 0, "QUALIFIED": 0, "ENRICHABLE": 0},
    }

    while not scheduler.is_empty():
        if search_deadline.is_exceeded() or (deadline and deadline.remaining() < 1.0):
            print(f"[company_discovery] Search phase deadline completed ({discovery_deadline.remaining():.1f}s remaining). Transitioning to directory & homepage crawling.")
            exit_reason = "Search phase deadline completed"
            break

        req = scheduler.next()
        if not req:
            break

        pname = req.provider
        page = req.meta.get("page", 0)
        max_results = req.meta.get("max_results", 10)
        page_offset = page * max_results

        family = req.meta.get("source", "unknown")
        task_discovery_mode = req.meta.get("discovery_mode", "expanded")
        
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
            # Execute search with bounded deadline
            raw_results = run_search(req.query, start=page_offset, family=family, deadline=search_deadline)
            from search.manager import get_search_manager
            manager = get_search_manager()
            is_cache_served = manager.last_provider_used == "cache"
            search_report = getattr(manager, "last_search_report", {}) or {}
            serpapi_primary_succeeded = any(
                provider.get("provider") == "serpapi" and provider.get("status") == "SUCCESS"
                for provider in search_report.get("providers", [])
            )
            if getattr(manager, "last_search_report", None):
                discovery_report["providers"].append(manager.last_search_report)
                for provider_info in manager.last_search_report.get("providers", []):
                    if provider_info.get("status") not in {"SUCCESS", "EMPTY"}:
                        stats.increment("provider_failures")
                    elif provider_info.get("status") == "EMPTY":
                        stats.increment("provider_empty_results")

            if is_cache_served:
                stats.increment("cache_served_queries")
            else:
                stats.increment("funnel_http_success")

        except Exception as e:
            # If the search layer signalled that all providers are exhausted,
            # bubble this up so the top-level pipeline can abort with a clear
            # DISCOVERY_UNAVAILABLE message instead of continuing silently.
            from search.exceptions import AllProvidersExhausted
            if isinstance(e, AllProvidersExhausted):
                print(f"[company_discovery] Discovery unavailable: {e}")
                raise
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
                if serpapi_primary_succeeded or getattr(config, "SERPAPI_PRIMARY_MODE", False):
                    # SerpApi primary mode handles discovery directly via organic results
                    print(f"[SERPAPI] Skipping directory result in SERPAPI_PRIMARY_MODE: {url}")
                    continue
                directory_urls_to_mine.append((url, result.get("title", ""), family))
                stats.increment("directory_queued")
                if DEBUG:
                    print(f"[Discovery] Queued directory for mining: {url}")
                continue

            from discovery.semantic_ranking_engine import SemanticRanker
            ranker = SemanticRanker()

            # Step 1: Snippet-level scoring (pass url for entity identity signals)
            sre_res = ranker.score_snippet(result.get("title", ""), result.get("snippet", ""), keyword, url=url)
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
                # Ambiguous/borderline snippet
                if getattr(config, "SERPAPI_PRIMARY_MODE", False):
                    # In SERPAPI_PRIMARY_MODE: bypass homepage HTML scraping; rely strictly on snippet scoring
                    if relevance_score < config.RELEVANCE_THRESHOLD_LOW:
                        stats.increment("rejected_results")
                        rejected_count_total += 1
                        print(f"[REJECTED] URL: {url} | Title: {result.get('title')!r} | Snippet: {result.get('snippet')!r} | Reason: Low snippet relevance score {relevance_score} (< {config.RELEVANCE_THRESHOLD_LOW})")
                        continue
                    result["classification"] = "ALLOW" if relevance_score >= config.RELEVANCE_THRESHOLD_HIGH else "LIKELY_COMPANY"
                    result["relevance_score"] = relevance_score
                    result["relevance_tier"] = tier
                    result["relevance_info"] = sre_res
                    if sre_res.get("industry") != "Unknown":
                        result["industry_detected"] = sre_res["industry"]
                elif homepage_evals < 10:
                    homepage_evals += 1
                    
                    from discovery.homepage_evaluator import _fetch_homepage
                    html = _fetch_homepage(url, deadline=deadline)
                    
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

            from query.intent_classifier import is_entity_query
            is_cat = not is_entity_query(keyword)
            if is_query_as_company(company_name, keyword, is_cat):
                rejected_count_total += 1
                print(f"[REJECTED] URL: {url} | Company: {company_name} | Reason: Company name identical to category query ('{keyword}')")
                continue

            # Entity searches must retain a result only when its domain or
            # LinkedIn company profile identifies the queried entity.  This
            # prevents titles such as "Create your Microsoft account" from
            # becoming companies merely because the query was "microsoft".
            if not is_cat and "linkedin.com/company/" not in url.lower():
                domain_token = _domain_token(url)
                entity_token = re.sub(r"[^a-z0-9]", "", keyword.lower())
                company_token = re.sub(r"[^a-z0-9]", "", company_name.lower())
                if not domain_token or not (
                    domain_token in entity_token
                    or entity_token in domain_token
                    or domain_token in company_token
                    or company_token in domain_token
                ):
                    rejected_count_total += 1
                    print(f"[REJECTED] URL: {url} | Company: {company_name} | Reason: Entity identity is not supported by the source domain")
                    continue

            stats.increment("discovery_candidates")

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
                "discovery_mode": task_discovery_mode,
            }

            # Attach URL to the right slot
            if "linkedin.com" in url:
                new_record["linkedin"] = url
            elif not _is_platform_domain(url) and not is_rejected_lead_domain(url):
                # For entity queries, verify domain token matches entity query or company name
                from query.intent_classifier import is_entity_query
                if is_entity_query(keyword):
                    dtok = _domain_token(url)
                    kw_slug = re.sub(r"[^a-z0-9]", "", keyword.lower())
                    comp_slug = re.sub(r"[^a-z0-9]", "", company_name.lower())
                    if dtok and (dtok in kw_slug or kw_slug in dtok or dtok in comp_slug or comp_slug in dtok):
                        new_record["website"] = get_root_company_url(url)
                    else:
                        print(f"[company_discovery] Rejected candidate website {url} for entity query '{keyword}' (domain token '{dtok}' does not match entity/company)")
                else:
                    new_record["website"] = get_root_company_url(url)

            if key not in accumulator:
                accumulator[key] = new_record
                unique_sources.add(source)
            else:
                stats.increment("duplicate_companies")
                accumulator[key] = best_company_record(
                    accumulator[key], new_record
                )
                unique_sources.add(accumulator[key]["source"])
            new_record["canonical_id"] = canonical_company_id(new_record)
            discovery_report["candidates"].append({
                "company": company_name,
                "url": url,
                "title": (result.get("title") or "")[:180],
                "provider": source,
                "classification": new_record["classification"],
                "relevance_score": relevance_score,
                "stage": "QUALIFIED",
                "reason": "identity_and_relevance",
            })
            discovery_report["stages"]["DISCOVERED"] = len(discovery_report["candidates"])
            discovery_report["stages"]["QUALIFIED"] = len(accumulator)
            discovery_report["stages"]["ENRICHABLE"] = sum(
                1 for candidate in accumulator.values()
                if candidate.get("website") or candidate.get("linkedin") or candidate.get("source_url")
            )
            stats.set_value("qualified_candidates", discovery_report["stages"]["QUALIFIED"])
            stats.set_value("enrichable_candidates", discovery_report["stages"]["ENRICHABLE"])
        
        # Enqueue next page if pagination is supported and current page yielded results
        if raw_results and page + 1 < config.MAX_SEARCH_PAGES:
            next_req = Request(
                url="search",
                query=req.query,
                provider=pname,
                priority=source_priorities.get(pname, 20),
                meta={
                    "page": page + 1,
                    "max_results": max_results,
                    "source": pname,
                    "depth": 1,
                    "discovery_mode": req.meta.get("discovery_mode", "expanded"),
                    "original_keyword": req.meta.get("original_keyword", keyword),
                }
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
        actual_provider = manager.last_provider_used if (hasattr(manager, "last_provider_used") and manager.last_provider_used) else provider_name
        print(f"[Discovery Stats] Source: {actual_provider:<20} | Query: '{req.query}' | Parsed: {parsed_count_total} | Accepted: {accepted_count_total} | Rejected: {rejected_count_total} | Time: {time_taken:.2f}s")

        # A successful SerpApi result set is the primary discovery path.  Once
        # it supplies the requested number of real candidates, do not spend
        # the remaining category-query budget or start directory mining.
        used_serpapi = "serpapi" in (actual_provider or "").lower()
        if used_serpapi and len(accumulator) >= target_companies:
            serpapi_sufficient = True
            directory_urls_to_mine.clear()
            print(f"[SERPAPI] Discovery target reached ({len(accumulator)}/{target_companies}); skipping remaining category discovery and directory mining.")
            exit_reason = f"SerpApi discovery target ({target_companies}) reached"
            break
        
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

        # Check discovery phase deadline
        if discovery_deadline.is_exceeded() or (deadline and deadline.remaining() < 1.0):
            print(f"[company_discovery] Stopping: Discovery phase deadline completed ({discovery_deadline.remaining():.1f}s remaining).")
            exit_reason = "Discovery deadline completed"
            break


        # Coverage saturation check (stop if last 5 queries yielded 0 new unique companies)
        if len(recent_yields) >= 5 and sum(list(recent_yields)[-5:]) == 0 and len(accumulator) >= 3:
            print("[company_discovery] Stopping: Coverage saturation reached (Last 5 queries yielded 0 new companies).")
            exit_reason = "Coverage saturation reached (5 zero-yield queries)"
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
    if getattr(config, "SERPAPI_PRIMARY_MODE", False) and directory_urls_to_mine:
        print(f"[Discovery] SERPAPI_PRIMARY_MODE: Bypassing directory queue ({len(directory_urls_to_mine)} directory URLs skipped)")
        directory_urls_to_mine.clear()
    from query.intent_classifier import is_entity_query
    if serpapi_sufficient and directory_urls_to_mine:
        # Defensive guard for queues populated before the final SerpApi query.
        print(f"[Discovery] Skipping directory queue after successful SerpApi discovery ({len(directory_urls_to_mine)} directory URLs skipped)")
        directory_urls_to_mine.clear()
    if is_entity_query(keyword):
        if directory_urls_to_mine:
            print(f"\n[Discovery] Skipping directory queue for entity query '{keyword}' ({len(directory_urls_to_mine)} directory URLs skipped)")
            directory_urls_to_mine.clear()

    if directory_urls_to_mine:
        dir_count = len(directory_urls_to_mine)
        # Workload-scaled adaptive directory budget (10 dirs -> 15s, 40 dirs -> 30s, 100 dirs -> 45s)
        dir_budget_s = min(45.0, max(15.0, dir_count * 1.5))
        print(f"\n[Discovery] Processing directory queue: {dir_count} directories collected (Adaptive Budget: {dir_budget_s:.1f}s)")
        
        # Create sub-deadline timer for directory phase
        dir_deadline = Deadline(min(dir_budget_s, deadline.remaining() if deadline else dir_budget_s))
        
        from discovery.directory_extractor import extract_company_links
        from discovery.homepage_evaluator import _fetch_homepage
        from concurrent.futures import ThreadPoolExecutor
        
        all_candidate_profiles = []
        
        def _mine_single_directory(item):
            if (dir_deadline and dir_deadline.is_exceeded()) or (deadline and deadline.is_exceeded()):
                return []
            dir_url, dir_title, dir_family = item
            print(f"[Discovery] Mining directory: {dir_url}")
            dir_html = _fetch_homepage(dir_url, deadline=dir_deadline)
            if not dir_html:
                print(f"[Discovery] Failed to fetch directory page: {dir_url}")
                return []
            extracted_links = extract_company_links(dir_html, dir_url)
            print(f"[Discovery] Extracted {len(extracted_links)} links from directory {dir_url}")
            stats.increment("directory_mined", len(extracted_links))
            return [(ext_url, dir_title, dir_family) for ext_url in extracted_links if ext_url not in processed_company_urls]

        mine_executor = ThreadPoolExecutor(max_workers=5)
        try:
            futures = [mine_executor.submit(_mine_single_directory, item) for item in directory_urls_to_mine]
            for f in futures:
                if (dir_deadline and dir_deadline.is_exceeded()) or (deadline and deadline.is_exceeded()):
                    print("[Discovery] Directory mining deadline reached, aborting remaining directory fetches.")
                    break
                try:
                    res = f.result(timeout=min(8.0, dir_deadline.remaining() if dir_deadline else 8.0))
                    if res:
                        all_candidate_profiles.extend(res)
                except Exception:
                    continue
        finally:
            mine_executor.shutdown(wait=False, cancel_futures=True)
                    
        # Interleave candidates by domain and prioritize High-confidence / relevant candidates first
        interleaved_candidates = interleave_urls_by_domain(all_candidate_profiles)
        
        # Sort candidates by title/url relevance priority (High -> Medium -> Low)
        def candidate_priority_key(cand):
            url, title, _ = cand
            from discovery.semantic_ranking_engine import SemanticRanker
            s_res = SemanticRanker().score_snippet(title, url, keyword)
            return s_res.get("score", 0.0)
            
        interleaved_candidates.sort(key=candidate_priority_key, reverse=True)
        
        # Limit candidate evaluation queue to avoid hammering directories and blowing budget
        max_eval = getattr(config, "MAX_DIRECTORY_CANDIDATES_TO_EVALUATE", 50)
        candidates_to_process = interleaved_candidates[:max_eval]
        print(f"[Discovery] Prioritized {len(interleaved_candidates)} directory candidate profiles by confidence score (High -> Medium -> Low).")
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
            if (dir_deadline and dir_deadline.is_exceeded()) or (deadline and deadline.is_exceeded()):
                return None
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
                eval_res = evaluate_url(ext_url, "", "", keyword, dir_family, deadline=dir_deadline)
                if eval_res:
                    return (cand, eval_res)
            except Exception as e:
                print(f"[Discovery] Error evaluating candidate {ext_url}: {e}")
            return None

        # Execute thread pool with non-blocking shutdown
        executor = ThreadPoolExecutor(max_workers=num_workers)
        try:
            futures = [executor.submit(evaluate_candidate, cand) for cand in candidates_to_process]
            
            for future in futures:
                if (dir_deadline and dir_deadline.is_exceeded()) or (deadline and deadline.is_exceeded()):
                    print("[Discovery] Directory evaluation deadline reached, aborting remaining directory candidates.")
                    break
                try:
                    res = future.result(timeout=min(10.0, dir_deadline.remaining() if dir_deadline else 10.0))
                except Exception:
                    continue
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
                from query.intent_classifier import is_entity_query
                is_cat = not is_entity_query(keyword)
                if is_query_as_company(company_name, keyword, is_cat):
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
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

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

    # ── Partial results snapshot (preserve work done so far) ───────────────
    try:
        import json as _json
        from datetime import datetime as _dt
        if accumulator or directory_urls_to_mine:
            os.makedirs("output", exist_ok=True)
            ts = _dt.now().strftime("%Y%m%d_%H%M%S")
            safe = keyword.replace(" ", "_").replace("/", "_").replace("\\", "_").lower().strip("_") or "partial"
            partial_path = os.path.join("output", f"partial_{safe}_{ts}.json")
            snapshot = {
                "keyword": keyword,
                "exit_reason": exit_reason,
                "accumulator_count": len(accumulator),
                "accumulator": list(accumulator.values())[:200],
                "directory_candidates": directory_urls_to_mine[:200],
                "remaining_tasks_preview": remaining[:20],
            }
            with open(partial_path, "w", encoding="utf-8") as _f:
                _json.dump(snapshot, _f, indent=2, ensure_ascii=False)
            print(f"[company_discovery] Partial results saved: {partial_path}")
    except Exception:
        # Do not let snapshot failures block discovery finalization
        pass

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
            evidence_ok, evidence_reason = minimum_evidence_gate(company)
            if not evidence_ok:
                stats.increment("rejected_results")
                print(f"[company_discovery] evidence-gate rejected {company.get('company')!r}: {evidence_reason}")
                continue
            intent_ok, intent_reason = company_intent_gate(company, keyword)
            if not intent_ok:
                partial_ok, partial_reason = partial_lead_gate(company, intent_reason)
                if not partial_ok:
                    stats.increment("rejected_results")
                    company["qualification_reason"] = intent_reason
                    discovery_report["candidates"].append({
                        "company": company.get("company"),
                        "url": company.get("source_url") or company.get("website") or company.get("linkedin"),
                        "stage": "REJECTED",
                        "reason": intent_reason,
                        "relevance_score": company.get("relevance_score", 0),
                    })
                    print(f"[company_discovery] intent-gate rejected {company.get('company')!r}: {intent_reason}")
                    continue
                company["qualification_reason"] = partial_reason
                company["discovery_stage"] = "PARTIAL"
                company["verification_status"] = "partial"
                print(f"[company_discovery] retaining partial lead {company.get('company')!r}: {partial_reason}")
            company["canonical_id"] = canonical_company_id(company)
            company.setdefault("discovery_stage", "ENRICHABLE")
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

    # For entity queries (e.g. "swiggy", "pizza hut"), consolidate onto the primary canonical entity
    from query.intent_classifier import is_entity_query
    if is_entity_query(keyword):
        kw_slug = re.sub(r"[^a-z0-9]", "", keyword.lower())
        entity_matches = [
            c for c in result
            if kw_slug == re.sub(r"[^a-z0-9]", "", (c.get("company") or "").lower())
            or kw_slug in re.sub(r"[^a-z0-9]", "", (c.get("company") or "").lower())
        ]
        if entity_matches:
            with_website = [c for c in entity_matches if c.get("website")]
            if with_website:
                # Merge any linkedin URL from other entity matches if missing
                for cand in entity_matches:
                    if cand.get("linkedin") and not with_website[0].get("linkedin"):
                        with_website[0]["linkedin"] = cand.get("linkedin")
                result = with_website[:1]
            else:
                result = entity_matches[:1]

            # If the canonical entity record has no website, resolve it via quick HTTP probe
            if result and not result[0].get("website"):
                cand = result[0]
                slugs = []
                if cand.get("linkedin"):
                    m = re.search(r"linkedin\.com/company/([a-z0-9\-]+)", cand["linkedin"].lower())
                    if m:
                        slugs.append(m.group(1).replace("-", ""))
                if kw_slug and kw_slug not in slugs:
                    slugs.append(kw_slug)
                
                import requests
                for s in slugs:
                    for host in (f"https://www.{s}.com", f"https://{s}.com"):
                        try:
                            probe = requests.get(
                                host,
                                timeout=3.5,
                                allow_redirects=True,
                                stream=True,
                                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                            )
                            if probe.status_code < 400:
                                final_url = probe.url
                                from urllib.parse import urlparse
                                p_dom = urlparse(final_url).netloc.lower()
                                if p_dom.startswith("www."):
                                    p_dom = p_dom[4:]
                                if s in p_dom:
                                    cand["website"] = final_url
                                    cand["domain"] = p_dom
                                    cand["relevance_tier"] = "HIGH"
                                    cand["source"] = "entity_resolution"
                                    print(f"[company_discovery] Resolved canonical domain for {keyword}: {final_url}")
                                    break
                        except Exception:
                            continue
                    if cand.get("website"):
                        break

        # Standardize entity company name to title casing if slug matches
        if result and is_entity_query(keyword):
            cand_name = result[0].get("company") or ""
            if kw_slug == re.sub(r"[^a-z0-9]", "", cand_name.lower()):
                result[0]["company"] = keyword.strip().title()

    stats.set_value("validated_companies", len(result))

    # ── Phase 1 Advanced Enrichment (Lead Score, Domain Intel, Org Graph) ──
    from utils.lead_scorer import compute_lead_score
    from utils.domain_intel import get_domain_intel
    from utils.org_graph import build_org_graph

    for record in result:
        try:
            domain = record.get("domain") or ""
            if not domain and record.get("website"):
                from urllib.parse import urlparse
                domain = urlparse(record["website"]).netloc.lower().lstrip("www.")

            if domain:
                record["domain_intel"] = get_domain_intel(domain)

            record["lead_score"] = compute_lead_score(record)
            record["org_graph"]  = build_org_graph(record)
        except Exception as exc:
            print(f"[company_discovery] Enrichment warning for {record.get('company')}: {exc}")

    if hasattr(manager, "_client") and hasattr(manager._client, "proxy_manager"):
        manager._client.proxy_manager.is_crawling = False

    discovery_report["stages"]["QUALIFIED"] = len(result)
    discovery_report["stages"]["ENRICHABLE"] = len(result)
    stats.set_value("discovery_report", discovery_report)
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
