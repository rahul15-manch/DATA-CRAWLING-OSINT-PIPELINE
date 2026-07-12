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

import re
import time
from urllib.parse import urlparse

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


def _is_non_company_domain(url: str) -> bool:
    """Return True for known educational/media/reference/tutorial domains (Task 6)."""
    token = _domain_token(url)
    if not token:
        return True
    if token in NON_COMPANY_DOMAINS:
        return True
    
    # Substring check for maximal filtering safety
    lowered_url = url.lower()
    for block in NON_COMPANY_DOMAINS:
        if block in lowered_url:
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


def should_ignore_result(result: dict) -> bool:
    """
    Filter obvious non-company search results before creating company records.

    A result is ignored when any of the following hold
    -------------------------------------------------
    1. Domain is in NON_COMPANY_DOMAINS  (hard block)
    2. Government domain (.gov, .gov.in, .gov.uk, …)
    3. Forum domain (Reddit, Quora, StackOverflow, Medium, Zhihu, …)
    4. Domain is a platform AND title is informational
    5. Title is informational AND no business signal in title
    6. URL path contains a strong educational sub-path signal
    """
    title = result.get("title") or ""
    url = result.get("url") or ""

    # 1. Hard-blocked domain
    if _is_non_company_domain(url):
        return True

    # 2 & 3. Government / Forum URL gate
    if not is_lead_url_valid(url):
        return True

    # 4. Platform page with informational title
    if _is_platform_domain(url) and _title_contains_informational_term(title):
        return True

    # 5. Informational title with no business signal
    if _title_contains_informational_term(title) and not _title_has_business_signal(title):
        return True

    # 6. Educational URL path
    if _url_path_contains_educational_signal(url):
        return True

    return False


def validate_company_record(company: dict) -> tuple:
    """
    Final validation of a discovered company record before lead-card creation.

    Returns (True, None) for valid records.
    Returns (False, reason_str) for rejected records.
    """
    name = company.get("company") or ""
    website = company.get("website") or ""

    if not name:
        return False, "missing company name"

    if len(name) < 2:
        return False, "company name too short"

    if _title_contains_informational_term(name):
        return False, "company name looks informational"

    if is_rejected_lead_domain(website):
        return False, "blocked non-company domain"

    # Reject government and forum URLs
    if website and not is_lead_url_valid(website):
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

    # 5. Use the last non-fragment candidate (typically the site name)
    non_fragment_candidates = [c for c in candidates if not _is_sentence_fragment(c)]
    if len(non_fragment_candidates) > 1:
        return non_fragment_candidates[-1]
    if non_fragment_candidates:
        return non_fragment_candidates[0]

    # 6. Final fallback
    return domain_name


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
    tasks = generate_search_tasks(keyword)
    stats.increment("queries_generated", len(tasks))

    # key → company dict (dedup by company name during accumulation)
    accumulator: dict[str, dict] = {}

    for page in range(config.MAX_SEARCH_PAGES):
        page_offset = page * config.MAX_COMPANIES_PER_QUERY
        page_had_results = False

        for task in tasks:
            start_time = time.time()
            try:
                raw_results = run_search(task.query, start=page_offset)
            except Exception as e:
                print(f"[company_discovery] search failed for query '{task.query}': {e}")
                raw_results = []
            
            time_taken = time.time() - start_time
            stats.increment("queries_executed")
            stats.increment("search_results", len(raw_results))

            if raw_results:
                page_had_results = True

            # Retrieve the provider name used for this query
            from discovery.search_backend import get_search_manager
            provider_name = get_search_manager().last_provider_used
            
            parsed_count = len(raw_results)
            accepted_count = 0
            rejected_count = 0

            for result in raw_results:
                url = result.get("url")
                if not url:
                    rejected_count += 1
                    continue

                if should_ignore_result(result):
                    stats.increment("rejected_results")
                    rejected_count += 1
                    continue

                company_name = guess_company_name(result)
                if not company_name:
                    rejected_count += 1
                    continue

                accepted_count += 1
                key = company_name.lower()
                source = detect_source(url)

                new_record = {
                    "company": company_name,
                    "website": None,
                    "linkedin": None,
                    "industry": keyword,
                    "location": None,
                    "source": source,
                }

                # Attach URL to the right slot
                if "linkedin.com" in url:
                    new_record["linkedin"] = url
                elif not _is_platform_domain(url):
                    new_record["website"] = url

                if key not in accumulator:
                    accumulator[key] = new_record
                else:
                    # Task 4: keep the higher-confidence source record
                    stats.increment("duplicate_companies")
                    accumulator[key] = best_company_record(
                        accumulator[key], new_record
                    )

            # Task 8: Print Provider query-level stats
            page_num = page + 1
            print(f"[Provider Stats] Provider: {provider_name:<20} | Query: '{task.query}' | Page: {page_num} | Parsed: {parsed_count} | Accepted: {accepted_count} | Rejected: {rejected_count} | Time: {time_taken:.2f}s")

        # Early exit when target reached
        if len(accumulator) >= config.TARGET_COMPANIES:
            print(
                f"[company_discovery] target {config.TARGET_COMPANIES} reached "
                f"on page {page + 1}"
            )
            break

        # Stop paginating when a page returned nothing useful
        if not page_had_results:
            print(f"[company_discovery] no results on page {page + 1}, stopping")
            break

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
            validated.append(company)
        else:
            stats.increment("rejected_results")
            print(
                f"[company_discovery] rejected {company.get('company')!r}"
                f": {reason}"
            )

    # ── Task 11: Normalize company names (merge variants) ─────────────────
    normalized = normalize_companies(validated)

    # ── Deduplicate by normalised name ────────────────────────────────────
    result = dedupe_companies(normalized)
    stats.set_value("validated_companies", len(result))

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
