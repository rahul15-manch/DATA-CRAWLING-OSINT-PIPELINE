
from __future__ import annotations

import os
import re
import time
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse, urlunparse

import config
from search.exceptions import AllProvidersExhausted, ProviderParseError, ProviderUnavailable
from search.provider_base import SearchProvider
from search.registry import DEFAULT_PRIORITY, PROVIDER_REGISTRY, ProviderRegistry
from search.result import SearchResult
from search_cache import SearchCache
from query.expansion import record_query_outcome

logger = logging.getLogger(__name__)


def is_valid_company_url(url: str) -> bool:
    if not url:
        return False
    url = url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        return False
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        if not netloc or "." not in netloc:
            return False
        # Reject search engine paths or internal searches
        path = parsed.path.lower()
        if path == "/search" or "search?q=" in url.lower() or "google.com" in netloc:
            return False
        # Reject local search files or search terms containing spaces or exclamation marks in host
        if " " in netloc or "!" in netloc:
            return False
        return True
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Per-provider statistics
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ProviderStats:
    """Collected metrics for a single provider during a pipeline run."""

    provider:         str
    queries:          int   = 0
    successful_queries: int = 0
    results_returned: int   = 0
    failures:         int   = 0
    parser_failures:  int   = 0
    fallback_count:   int   = 0
    total_latency_s:  float = 0.0
    leads_discovered:  int   = 0
    business_accepted: int   = 0
    latencies:        list[float] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        """Fraction of queries that returned at least one result (0.0–1.0)."""
        if self.queries == 0:
            return 0.0
        return self.successful_queries / self.queries

    @property
    def avg_latency_s(self) -> float:
        if self.queries == 0:
            return 0.0
        return self.total_latency_s / self.queries

    def summary_line(self) -> str:
        return (
            f"  {self.provider:<20}"
            f"  queries={self.queries}"
            f"  successes={self.successful_queries}"
            f"  results={self.results_returned}"
            f"  failures={self.failures}"
            f"  parser_failures={self.parser_failures}"
            f"  fallbacks={self.fallback_count}"
            f"  success_rate={self.success_rate:.0%}"
            f"  avg_latency={self.avg_latency_s:.2f}s"
            f"  leads={self.leads_discovered}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# URL canonicalization
# ─────────────────────────────────────────────────────────────────────────────

# UTM and tracking params to strip before deduplication
_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "referrer", "source", "fbclid", "gclid", "msclkid", "mc_cid",
    "mc_eid", "_ga", "yclid", "dclid",
})


def _canonicalize_url(url: str) -> str:
    """
    Normalize a URL so that semantically identical URLs deduplicate.

    Transformations
    ---------------
    1. Lowercase scheme and host
    2. Strip www. prefix
    3. Remove trailing slash from path (unless path is just "/")
    4. Remove tracking / UTM query parameters
    5. Sort remaining query parameters for stable comparison
    6. Drop empty fragments

    Examples
    --------
    https://Example.com/            → https://example.com
    https://www.example.com         → https://example.com
    https://example.com?utm_source=google → https://example.com
    https://example.com/page/       → https://example.com/page
    """
    try:
        parsed = urlparse(url.strip())

        scheme  = parsed.scheme.lower()
        netloc  = parsed.netloc.lower()

        # Strip www.
        if netloc.startswith("www."):
            netloc = netloc[4:]

        path    = parsed.path.rstrip("/") or ""
        # Preserve root "/" for domains like "https://example.com/"
        # → empty path is fine; just don't duplicate slashes

        # Strip tracking params, sort remaining
        if parsed.query:
            qs_pairs = [
                (k, v)
                for k, vals in parse_qs(parsed.query, keep_blank_values=False).items()
                if k not in _TRACKING_PARAMS
                for v in vals
            ]
            qs_pairs.sort()
            query = "&".join(f"{k}={v}" for k, v in qs_pairs)
        else:
            query = ""

        canonical = urlunparse((scheme, netloc, path, "", query, ""))
        return canonical

    except Exception:
        # If anything goes wrong return the original (never crash deduplication)
        return url.strip()


# ── Intent scoring weights ────────────────────────────────────────────────────
# Positive signals push a query toward Google (HIGH/MEDIUM)
# Negative signals push it toward Bing-direct (LOW)

_SCORE_OPERATOR_SITE    = 4   # site: operator → always Google (dork)
_SCORE_OPERATOR_OTHER   = 3   # inurl:, intitle:, "..." exact phrase
_SCORE_PERSON_LOOKUP    = 3   # founder, CEO, director, co-founder
_SCORE_LINKEDIN         = 3   # linkedin.com or site:linkedin.com
_SCORE_COMPANY_NOUN     = 2   # company, agency, firm, pvt, ltd, inc, startup
_SCORE_INDUSTRY_LOC     = 2   # industry + location pair
_SCORE_DIRECTORY        = 2   # justdial, indiamart, yellowpages etc.
_SCORE_INFORMATIONAL    = -3  # ideas, tips, how to, what is, tutorial

# Score thresholds
_THRESHOLD_HIGH   = 4
_THRESHOLD_MEDIUM = 2

_PERSON_TERMS = frozenset({
    "founder", "ceo", "co-founder", "cofounder", "director",
    "cto", "coo", "vp", "vice president", "head of",
    "our team", "about us", "meet the team", "leadership",
})
_COMPANY_NOUNS = frozenset({
    "company", "companies", "agency", "agencies", "firm", "firms",
    "startup", "startups", "services", "pvt", "ltd", "inc",
    "llp", "corporation", "enterprise", "enterprises",
})
_DIRECTORY_TERMS = frozenset({
    "justdial", "indiamart", "yellowpages", "sulekha",
    "tradeindia", "exportersindia", "linkedin",
})
_INFORMATIONAL_TERMS = frozenset({
    "ideas", "tips", "how to", "what is", "tutorial",
    "guide", "learn", "best practices", "examples",
})


def _classify_query_intent(query: str) -> str:
    """
    Score-based intent classifier.

    Returns
    -------
    "HIGH"   — route to Google first (score >= _THRESHOLD_HIGH)
    "MEDIUM" — route to Google, fallback to Bing on failure (score >= _THRESHOLD_MEDIUM)
    "LOW"    — skip Google, go directly to Bing
    """
    q_lower = query.lower()
    score = 0

    # Search operators — strongest signal
    if "site:" in q_lower:
        score += _SCORE_OPERATOR_SITE
    if any(op in q_lower for op in ("inurl:", "intitle:", "intext:")):
        score += _SCORE_OPERATOR_OTHER
    # Exact phrase operator
    if '"' in query:
        score += _SCORE_OPERATOR_OTHER

    # Person / professional lookup
    if any(term in q_lower for term in _PERSON_TERMS):
        score += _SCORE_PERSON_LOOKUP

    # LinkedIn
    if "linkedin" in q_lower:
        score += _SCORE_LINKEDIN

    # Company nouns
    if any(noun in q_lower for noun in _COMPANY_NOUNS):
        score += _SCORE_COMPANY_NOUN

    # Directory sources
    if any(d in q_lower for d in _DIRECTORY_TERMS):
        score += _SCORE_DIRECTORY

    # Informational / low-value signals
    if any(t in q_lower for t in _INFORMATIONAL_TERMS):
        score += _SCORE_INFORMATIONAL

    if score >= _THRESHOLD_HIGH:
        return "HIGH"
    elif score >= _THRESHOLD_MEDIUM:
        return "MEDIUM"
    else:
        return "LOW"


def is_high_priority_query(query: str) -> bool:
    """
    Backward-compatible wrapper.
    Returns True for HIGH and MEDIUM intent queries (both route to Google).
    Returns False only for genuinely low-value queries.
    """
    return _classify_query_intent(query) in ("HIGH", "MEDIUM")


class SearchManager:
    """
    Coordinates all provider interactions for the Flowiz search layer.

    Usage
    -----
    manager = SearchManager()
    results = manager.search("automation company", max_results=10)

    Each element of `results` is a SearchResult with all metadata fields set.
    For backward compatibility, call .to_dict() to get a plain dict.
    """

    def __init__(self) -> None:
        # ── Provider priority list (env-configurable) ─────────────────────
        raw_priority: str = getattr(
            config, "SEARCH_PROVIDER_PRIORITY",
            ",".join(DEFAULT_PRIORITY),
        )
        # Support both list (if already parsed by config.py) and raw string
        if isinstance(raw_priority, list):
            self._priority: list[str] = [p.strip() for p in raw_priority if p.strip()]
        else:
            self._priority = [p.strip() for p in raw_priority.split(",") if p.strip()]

        # ── Provider mode ─────────────────────────────────────────────────
        self._mode: str = getattr(config, "SEARCH_PROVIDER", "auto").strip().lower()

        # ── Lazy provider instance cache ──────────────────────────────────
        self._instances: dict[str, SearchProvider] = {}

        # ── Health tracking — providers are cooled down, not permanently disabled ──
        # provider_health tracks whether a provider is currently available.
        self.provider_health: dict[str, bool] = {
            name: True for name in PROVIDER_REGISTRY
        }
        # Cooldown timestamps: { "bing": 1720000000.0 } means Bing cools until that time
        self._provider_cooldowns: dict[str, float] = {}
        self._provider_cooldown_secs: int = getattr(config, "PROVIDER_COOLDOWN_SECONDS", 300)
        
        self._bing_cooldown_step = 0
        self._bing_cooldown_sequence = [30, 60, 120, 300]

        # Circuit Breaker states and failure score trackers
        from collections import defaultdict
        self._provider_breaker_states: dict[str, str] = {
            name: "CLOSED" for name in PROVIDER_REGISTRY
        }
        self._provider_failure_scores: dict[str, float] = defaultdict(float)

        # ── Per-provider statistics ───────────────────────────────────────
        self.stats: dict[str, ProviderStats] = {
            name: ProviderStats(provider=name) for name in PROVIDER_REGISTRY
        }
        self._consecutive_zero_results: dict[str, int] = defaultdict(int)
        
        # ── Keyword-level state (Budget & Yield) ──────────────────────────
        self._keyword_queries: dict[str, int] = defaultdict(int)
        self._keyword_accepted: dict[str, int] = defaultdict(int)
        self._keyword_results: dict[str, int] = defaultdict(int)
        self._consecutive_captchas: dict[str, int] = defaultdict(int)
        
        # Provider query budgets
        self.provider_budgets = {
            "google_html": 8,
            "duckduckgo": 4,
            "bing": 2
        }

        # Per-provider live query counter for round-robin rotation.
        # Tracks how many times each provider has been the *first tried* this session,
        # so _get_ordered_providers can rotate the most-used provider to the back.
        self._provider_live_query_count: dict[str, int] = defaultdict(int)

        # ── Totals ────────────────────────────────────────────────────────
        self.total_queries:            int = 0
        self.total_results:            int = 0
        self.total_duplicates_removed: int = 0
        self.total_merged:             int = 0

        # For backward compatibility — tracks which provider(s) served last call
        self.last_provider_used: str = "none"

        # Search cache & stability settings
        cache_enabled = getattr(config, "CACHE_ENABLED", getattr(config, "ENABLE_SEARCH_CACHE", True))
        force_live = bool(getattr(config, "FORCE_LIVE_SEARCH", False))
        cache_ttl = getattr(config, "SEARCH_CACHE_TTL", 86400)
        cache_file = getattr(config, "SEARCH_CACHE_FILE", "search_cache.json")
        cache_namespace = getattr(config, "SEARCH_CACHE_NAMESPACE", "default")
        zero_result_ttl = getattr(config, "ZERO_RESULT_TTL", 1800)
        cache_zero_results = getattr(config, "CACHE_ZERO_RESULTS", False)
        self.cache_enabled = bool(cache_enabled) and not force_live
        self.cache = SearchCache(
            cache_file,
            cache_ttl,
            self.cache_enabled,
            namespace=cache_namespace,
            zero_result_ttl=zero_result_ttl,
            cache_zero_results=cache_zero_results,
        )

        self.cache_hits = 0
        self.cache_misses = 0
        self.cache_zero_hits = 0
        self.cache_expired = 0
        self.cache_bypasses = 0
        self.cache_debug_bypasses = 0

        # ── Reporting statistics ──────────────────────────────────────────
        self.google_queries = 0
        self.google_successes = 0
        self.google_429s = 0
        self.google_captchas = 0
        self.google_fallbacks = 0
        self.google_retries = 0
        self.google_parser_fail_queries = 0    # queries where all parsers failed
        self.google_enable_js_queries = 0      # queries hitting EnableJS page
        self.google_zero_result_queries = 0    # legitimate zero-result queries

        self.bing_queries = 0
        self.bing_successes = 0
        self.bing_failures = 0
        self.bing_recovery_count = 0           # times Bing recovered from cooldown

        # ── Yield analysis counters ───────────────────────────────────────
        self.queries_deduplicated = 0          # duplicate queries prevented
        self.queries_live_run = 0              # queries actually executed (not cache)
        self.queries_zero_results = 0          # live queries returning 0 results
        self.queries_parser_fail = 0           # queries ending in parser failure
        self.queries_google_blocked = 0        # queries where Google was blocked
        self.queries_bing_blocked = 0          # queries where Bing was blocked
        self.queries_skipped_circuit = 0       # queries skipped due to open circuit

        # ── Company source breakdown ──────────────────────────────────────
        # { "linkedin.com": 5, "justdial.com": 3, ... }
        self.source_breakdown: dict[str, int] = {}

        # ── Detailed Google response classification stats ──────────────────
        self.google_requests_sent = 0
        self.google_successful_serps = 0
        self.google_parser_failures = 0
        self.google_consent_pages = 0
        self.google_enablejs_pages = 0
        self.google_sorry_pages = 0
        self.google_unknown_layouts = 0
        self.google_html_sizes: list[int] = []

        # Thread-local storage to hold last request diagnostic info
        import threading
        self._last_diag = threading.local()
        self._last_diag.status_code = None
        self._last_diag.proxy = None
        self._last_diag.session_id = None
        self._last_diag.retry_count = None
        self._last_diag.retry_reasons = []

        from network_client_project.network import signals

        def _on_request_completed(request, response):
            self._last_diag.status_code = getattr(response, "status_code", 200)
            self._last_diag.proxy = request.proxy or "direct"
            self._last_diag.session_id = request.meta.get("session_id", "default")
            self._last_diag.retry_count = request.meta.get("retry_times", 0)
            self._last_diag.retry_reasons = request.meta.get("retry_reasons", [])

        def _on_request_failed(request, exception):
            self._last_diag.status_code = getattr(exception, "status_code", 0) or 500
            self._last_diag.proxy = request.proxy or "direct"
            self._last_diag.session_id = request.meta.get("session_id", "default")
            self._last_diag.retry_count = request.meta.get("retry_times", 0)
            self._last_diag.retry_reasons = request.meta.get("retry_reasons", [])

        signals.connect(_on_request_completed, signals.REQUEST_COMPLETED)
        signals.connect(_on_request_failed, signals.REQUEST_FAILED)

        from utils.budget_manager import ProviderBudgetManager
        self.budget_manager = ProviderBudgetManager()
        self._consecutive_blocks = defaultdict(int)
        self._google_disabled_until = 0.0

    # ── Public API ────────────────────────────────────────────────────────────

    def providers_available(self) -> bool:
        """
        Check if any active provider is available (not in cooldown).
        Used by the pipeline to pause discovery instead of hammering dead proxies.
        """
        self._recover_cooled_providers() # Ensure cooldowns are current
        for name in self._priority:
            if self.provider_health.get(name, False) and name not in self._provider_cooldowns:
                return True
        return False

    def providers_available_for_keyword(self, family: str = "unknown") -> bool:
        """
        Check if any active provider is available and not exhausted for this keyword and family.
        """
        self._recover_cooled_providers()
        for pname in self._priority:
            if not self.provider_health.get(pname, False):
                continue
            if pname in self._provider_cooldowns:
                continue
            
            # Check family-level zero stopping
            zeroes = self._consecutive_zero_results.get((pname, family), 0)
            if zeroes >= 3:
                if pname == "google_html":
                    total_accepted = self._keyword_accepted.get((pname, family), 0)
                    total_results = max(1, self._keyword_results.get((pname, family), 0))
                    overall_yield = total_accepted / total_results
                    if overall_yield < 0.10:
                        continue
                else:
                    continue
                    
            if pname == "bing" and self._consecutive_captchas.get("bing", 0) >= 2:
                continue
                
            return True
        return False



    def reset_keyword_state(self):
        """Reset the budget and early stopping counters for a new keyword."""
        self._keyword_queries.clear()
        self._keyword_accepted.clear()
        self._keyword_results.clear()
        self._consecutive_zero_results.clear()
        self._consecutive_captchas.clear()

    def search(
        self,
        query: str,
        max_results: int = 10,
        page: int = 0,
        family: str = "unknown",
    ) -> list[SearchResult]:
        self.total_queries += 1
        debug_mode = os.getenv("DISCOVERY_DEBUG", "false").lower() == "true"

        # 1. Check Query Cache
        if not self.cache_enabled:
            self.cache.stats["debug_bypasses"] += 1
            self.cache.stats["bypasses"] += 1
            print(f"[SearchManager] Cache disabled for: '{query}' (Page {page})")
        cached_dicts = self.cache.get(query, max_results, page)
        if cached_dicts is not None:
            self.cache_hits += 1
            self.cache_zero_hits = self.cache.get_stats().get("zero_result_hits", 0)
            print(f"[SearchManager] Cache HIT for query: '{query}'")
            print(f"[SearchManager] Cache HIT for: '{query}' (Page {page})")
            results = [SearchResult.from_dict(d) for d in cached_dicts]
            for global_rank, r in enumerate(results, start=1):
                r.rank = global_rank
            self.total_results += len(results)
            self.total_merged += len(results)
            self.last_provider_used = "cache"
            return results

        if self.cache_enabled:
            self.cache_misses += 1
            print(f"[SearchManager] Cache MISS for: '{query}' (Page {page})")
        else:
            self.cache_bypasses += 1
            print(f"[SearchManager] Cache bypassed for: '{query}' (Page {page})")
            
        limit = getattr(config, "GLOBAL_QUERY_LIMIT", 50)
        if limit > 0 and self.queries_live_run >= limit:
            print(f"[SearchManager] GLOBAL_QUERY_LIMIT ({limit}) reached. Skipping query: '{query}'")
            return []
            
        self.queries_live_run += 1

        # 2. Query Classification & Provider selection
        intent = _classify_query_intent(query)
        is_high = intent in ("HIGH", "MEDIUM")
        print(f"[SearchManager] Query: '{query}' | Intent: {intent}")

        ordered = self._get_ordered_providers()

        # Bypass Google for low-priority queries
        if not is_high:
            filtered = [p for p in ordered if "google" not in p.name.lower()]
            if len(filtered) < len(ordered):
                print(f"[SearchManager] LOW intent — bypassing Google, routing to Bing.")
            ordered = filtered

        # Recover providers that have completed their cooldown period
        self._recover_cooled_providers()

        active_providers = [p.name for p in ordered]
        print(f"[SearchManager] Provider order: {active_providers}")

        all_results:   list[SearchResult] = []
        providers_used: list[str]         = []
        seen_canonical: set[str]          = set()
        query_start_t = time.time()

        for provider in ordered:
            from utils.deadline import Deadline
            if Deadline.is_exceeded():
                print(f"[SearchManager] Global deadline exceeded. Returning {len(all_results)} partial results.")
                break
            pname = provider.name

            # Skip providers that are in cooldown
            if not self.provider_health.get(pname, True):
                print(f"[SearchManager] Skipping {pname!r} (in cooldown)")
                continue

            # Cooldown / consecutive blocks check for Google
            if pname == "google_html":
                if self._consecutive_blocks["google_html"] >= 3:
                    if time.time() < self._google_disabled_until:
                        remaining_cooldown = int(self._google_disabled_until - time.time())
                        print(f"[SearchManager] Skipping google_html (Disabled globally for {remaining_cooldown}s due to 3 consecutive blocks)")
                        continue
                    else:
                        self._consecutive_blocks["google_html"] = 0

            # Provider budget check via ProviderBudgetManager
            self.budget_manager.start_provider(pname)
            if not self.budget_manager.can_execute(pname):
                print(f"[SearchManager] Skipping {pname} (Budget or deadline check failed)")
                continue

            # 2. Bing Captcha Early Stop
            if pname == "bing" and self._consecutive_captchas["bing"] >= 2:
                print(f"[SearchManager] Skipping bing (Early stopping: >= 2 consecutive captchas)")
                continue

            # 3. Google Adaptive Early Stop
            if pname == "google_html":
                zeroes = self._consecutive_zero_results.get((pname, family), 0)
                if zeroes >= 3:
                    # Calculate overall yield
                    total_accepted = self._keyword_accepted.get((pname, family), 0)
                    total_results = max(1, self._keyword_results.get((pname, family), 0))
                    overall_yield = total_accepted / total_results
                    if overall_yield < 0.10:
                        print(f"[SearchManager] Skipping google_html for family {family} (Adaptive Stop: {zeroes} zeroes, yield {overall_yield:.2%})")
                        continue
            else:
                # Fallback zero-result cutoff for others
                if self._consecutive_zero_results.get((pname, family), 0) >= 3:
                    print(f"[SearchManager] Skipping {pname!r} for family {family} (Early stopping: >= 3 consecutive zero results)")
                    continue

            self._keyword_queries[pname] += 1
            self._provider_live_query_count[pname] += 1  # feeds round-robin rotation

            t0 = time.time()
            self._last_diag.status_code = None
            self._last_diag.proxy = None
            self._last_diag.session_id = None
            self._last_diag.retry_count = None
            self.stats[pname].queries += 1
            if pname == "google_html":
                self.google_queries += 1
            elif pname == "bing":
                self.bing_queries += 1

            try:
                print(
                    f"[SearchManager] [{pname}] query='{query}'"
                    f" max_results={max_results} page={page}"
                )
                raw = provider.search(query, max_results=max_results, page=page)
                latency = time.time() - t0
                self.stats[pname].total_latency_s += latency
                self.stats[pname].latencies.append(latency)
                self.stats[pname].results_returned += len(raw)

                from discovery.company_discovery import classify_result, should_ignore_result

                # Merge into all_results, deduplicating by canonical URL
                accepted = 0
                rejected_reasons: dict[str, int] = defaultdict(int)
                for r in raw:
                    if not r.url or not is_valid_company_url(r.url):
                        print(f"[SearchManager Reject] URL: {r.url} | Title: {r.title} | Reason: Invalid company URL pattern")
                        continue
                    result_dict = {"title": r.title or "", "url": r.url or "", "snippet": r.snippet or ""}
                    classification, reason = classify_result(result_dict)
                    if should_ignore_result(result_dict):
                        rejected_reasons[reason or classification or "UNKNOWN"] += 1
                        print(f"[SearchManager Reject] URL: {r.url} | Title: {r.title} | Reason: Ignored by classification ({classification} - {reason})")
                        continue

                    canon = _canonicalize_url(r.url)
                    if canon in seen_canonical:
                        self.total_duplicates_removed += 1
                        print(f"[SearchManager Reject] URL: {r.url} | Title: {r.title} | Reason: Duplicate canonical URL ({canon})")
                        continue
                    seen_canonical.add(canon)
                    all_results.append(r)
                    accepted += 1
                    self._track_source(r.url)

                providers_used.append(pname)

                top_rejection = max(rejected_reasons.items(), key=lambda item: item[1], default=("NONE", 0))[0]
                query_dur = time.time() - query_start_t
                if debug_mode:
                    print(f"[SearchManager] Query: {query}")
                    print(f"[SearchManager] Provider: {pname}")
                    print(f"[SearchManager] Results Parsed: {len(raw)}")
                    print(f"[SearchManager] Accepted: {accepted}")
                    print(f"[SearchManager] Rejected: {len(raw) - accepted}")
                    print(f"[SearchManager] Top rejection: {top_rejection}")
                    print(f"[SearchManager] Execution time: {latency:.2f}s")
                status_code = getattr(self._last_diag, "status_code", None) or 200
                proxy_used = getattr(self._last_diag, "proxy", None) or "direct"
                session_id = getattr(self._last_diag, "session_id", None) or "default"
                retry_count = getattr(self._last_diag, "retry_count", None) or 0
                is_cache_served = False
                retry_reasons = getattr(self._last_diag, "retry_reasons", [])
                reasons_str = ", ".join(retry_reasons) if retry_reasons else "None"
                from utils.deadline import Deadline
                print(
                    f"[QUERY DETAIL] Provider: {pname} | Query: '{query}' | Latency: {latency:.2f}s "
                    f"| Retry count: {retry_count} | Reason for retry: {reasons_str} "
                    f"| Reason for rejection: {top_rejection} | Switch reason: None (Success) "
                    f"| Remaining budget: {Deadline.remaining():.1f}s"
                )

                try:
                    from query.expansion import get_query_feedback_weight
                    roi_weight = get_query_feedback_weight(query)
                except Exception:
                    roi_weight = 1.0

                print(
                    f"[SearchManager] DIAG | provider={pname} | query='{query}' | latency={latency:.2f}s "
                    f"| http_status={status_code} | parsed={len(raw)} | accepted={accepted} "
                    f"| rejection_reason={top_rejection} | proxy={proxy_used} | session_id={session_id} "
                    f"| cache_hit={is_cache_served} | retry_count={retry_count} | roi_weight={roi_weight:.4f}"
                )

                self.stats[pname].business_accepted += accepted

                from stats.provider_stats import provider_stats

                if accepted == 0:
                    self.queries_zero_results += 1
                    self._consecutive_zero_results[(pname, family)] += 1
                    self._keyword_results[(pname, family)] += len(raw)
                    record_query_outcome(query, "zero_result", 0, provider=pname)
                    provider_stats.record_search_outcome(pname, zero_results=True)
                    if pname == "google_html":
                        self.google_zero_result_queries += 1
                        self._consecutive_blocks["google_html"] = 0
                        print(f"[SearchManager] GoogleHtml valid zero results.")
                    if not all_results:
                        self.cache.set(query, max_results, page, pname, [], kind="zero_result")

                    # Score suspicious zero results (expectation >= 0.5)
                    try:
                        from search.google_scheduler import get_query_expectation_score
                        exp_score = get_query_expectation_score(query)
                    except Exception:
                        exp_score = 0.5

                    if exp_score >= 0.5:
                        self._record_provider_failure_score(pname, 1.0, f"VALID_ZERO_RESULTS for high expectation query ({exp_score:.2f})")
                else:
                    self.stats[pname].successful_queries += 1
                    self._consecutive_zero_results[(pname, family)] = 0
                    if pname == "google_html":
                        self._consecutive_blocks["google_html"] = 0
                    self._keyword_accepted[(pname, family)] += accepted
                    self._keyword_results[(pname, family)] += len(raw)
                    record_query_outcome(query, "search_hit", len(raw), provider=pname)
                    provider_stats.record_search_outcome(pname, organic_results=len(raw), accepted_companies=accepted)
                    self.cache.set(query, max_results, page, pname, all_results, kind="success")

                    # Handle success transition for circuit breaker
                    breaker_state = self._provider_breaker_states.get(pname, "CLOSED")
                    if breaker_state == "HALF_OPEN":
                        self._provider_breaker_states[pname] = "CLOSED"
                        self._provider_failure_scores[pname] = 0.0
                        logger.info(f"[SearchManager] Probe query succeeded. {pname} breaker is now CLOSED (healthy).")
                        print(f"[SearchManager] Probe query succeeded. {pname} breaker is now CLOSED (restored).")
                    elif breaker_state == "CLOSED":
                        self._provider_failure_scores[pname] = max(0.0, self._provider_failure_scores[pname] - 1.0)

                if pname == "bing":
                    self.bing_successes += 1
                    self._bing_cooldown_step = 0

                # In auto mode: one successful provider with results is enough
                if self._mode == "auto" and accepted > 0:
                    break

                # If we have enough results, stop
                if len(all_results) >= max_results:
                    break

            except ProviderUnavailable as exc:
                latency = time.time() - t0
                if pname == "google_html" and "Circuit Breaker is OPEN" in exc.reason:
                    self.queries_skipped_circuit += 1
                    self.google_queries -= 1
                    self.stats[pname].queries -= 1
                    # Do not log/add stats
                else:
                    retry_count = getattr(self._last_diag, "retry_count", 0) or 0
                    retry_reasons = getattr(self._last_diag, "retry_reasons", [])
                    reasons_str = ", ".join(retry_reasons) if retry_reasons else "None"
                    from utils.deadline import Deadline

                    is_permanent = exc.reason in ("ENABLE_JS", "CAPTCHA", "CONSENT_PAGE", "FORBIDDEN")
                    decision = "Permanent failure" if is_permanent else "Transient failure"
                    current_idx = ordered.index(provider) if provider in ordered else -1
                    fallback_p = ordered[current_idx + 1].name if current_idx != -1 and current_idx + 1 < len(ordered) else "None"

                    print(
                        f"[QUERY DETAIL] Provider: {pname} | Failure: {exc.reason} | Decision: {decision} "
                        f"| Fallback: {fallback_p} | Remaining budget: {Deadline.remaining():.1f}s | Latency: {latency:.2f}s"
                    )

                    self.stats[pname].total_latency_s += latency
                    self.stats[pname].latencies.append(latency)
                    self.stats[pname].failures += 1
                    record_query_outcome(query, "unavailable", 0, provider=pname)

                    if "No healthy" in exc.reason and "proxies" in exc.reason:
                        print(f"[SearchManager] Disabling {pname} globally due to proxy exhaustion.")
                        self.provider_health[pname] = False

                    if pname == "google_html":
                        self.google_fallbacks += 1
                        self.queries_google_blocked += 1
                        is_block = any(term in exc.reason for term in ("ENABLE_JS", "CAPTCHA", "CONSENT_PAGE", "FORBIDDEN", "RATE_LIMIT", "429", "sorry", "unusual traffic"))
                        if is_block:
                            self._consecutive_blocks["google_html"] += 1
                            if self._consecutive_blocks["google_html"] >= 3:
                                self._google_disabled_until = time.time() + 600.0
                                print(f"[SearchManager] GoogleHtml consecutive blocks count reached 3. Disabling Google globally for 10 minutes.")
                    elif pname == "bing":
                        self.bing_failures += 1
                        self.queries_bing_blocked += 1
                        if "captcha" in exc.reason.lower() or "block" in exc.reason.lower():
                            self._consecutive_captchas["bing"] += 1

                    # General score-based circuit breaker scoring for ProviderUnavailable
                    reason_lower = exc.reason.lower()
                    points = 3.0
                    reason_lbl = f"Unavailable ({exc.reason[:30]})"

                    if "403" in reason_lower or "forbidden" in reason_lower:
                        points = 5.0
                        reason_lbl = "403 Forbidden"
                    elif "429" in reason_lower or "too many requests" in reason_lower or "sorry" in reason_lower or "unusual traffic" in reason_lower:
                        points = 4.0
                        reason_lbl = "429 Rate Limit"
                    elif "captcha" in reason_lower or "block" in reason_lower:
                        points = 3.0
                        reason_lbl = "Captcha/Block"

                    if pname == "bing" and "consent" in reason_lower:
                        print("[SearchManager] Bing hit a consent wall. Skipping failure score penalty.")
                    else:
                        self._record_provider_failure_score(pname, points, reason_lbl)

                current_idx = self._priority.index(pname) if pname in self._priority else -1
                next_pname = "None (Exhausted)"
                if current_idx != -1 and current_idx + 1 < len(self._priority):
                    next_pname = self._priority[current_idx + 1]

                print(f"[SearchManager] {pname} unavailable: {exc.reason} | Switching to {next_pname}")

                try:
                    for next_name in self._priority[current_idx + 1:]:
                        if next_name in self.stats:
                            self.stats[next_name].fallback_count += 1
                except ValueError:
                    pass
                continue

            except ProviderParseError as exc:
                from stats.provider_stats import provider_stats
                provider_stats.record_search_outcome(pname, parser_success=False)
                
                latency = time.time() - t0
                self.stats[pname].total_latency_s += latency
                self.stats[pname].latencies.append(latency)
                self.stats[pname].parser_failures += 1
                record_query_outcome(query, "parser_failure", 0)

                if pname == "google_html":
                    self.google_fallbacks += 1
                    self.queries_parser_fail += 1
                    self.google_parser_fail_queries += 1
                    if "unknown layout" in exc.reason.lower():
                        self.google_unknown_layouts += 1
                    print(f"[SearchManager] GoogleHtml parser failure.")
                elif pname == "bing":
                    self.queries_parser_fail += 1
                    print(f"[SearchManager] Bing parser failure (likely A/B layout). Not entering cooldown.")

                # Record parser failure score for circuit breaker
                if pname == "bing":
                    pass
                else:
                    self._record_provider_failure_score(pname, 3.0, f"Parser Failure ({exc.reason[:30]})")

                current_idx = self._priority.index(pname) if pname in self._priority else -1
                next_pname = "None (Exhausted)"
                if current_idx != -1 and current_idx + 1 < len(self._priority):
                    next_pname = self._priority[current_idx + 1]

                print(f"[SearchManager] {pname} parser error: {exc.reason} | Switching to {next_pname}")

                try:
                    for next_name in self._priority[current_idx + 1:]:
                        if next_name in self.stats:
                            self.stats[next_name].fallback_count += 1
                except (ValueError, IndexError):
                    pass
                continue

        # Rank final results
        for global_rank, r in enumerate(all_results, start=1):
            r.rank = global_rank
        self.total_results += len(all_results)
        self.total_merged += len(all_results)
        if providers_used:
            self.last_provider_used = "+".join(providers_used)
        else:
            self.last_provider_used = "none"

        return all_results


    def _enter_cooldown(self, pname: str) -> None:
        """Put a provider into timed cooldown (transition breaker to OPEN)."""
        if pname == "bing":
            secs = self._bing_cooldown_sequence[min(self._bing_cooldown_step, len(self._bing_cooldown_sequence)-1)]
            self._bing_cooldown_step += 1
        else:
            secs = self._provider_cooldown_secs

        until = time.time() + secs
        self._provider_cooldowns[pname] = until
        self.provider_health[pname] = False
        self._provider_breaker_states[pname] = "OPEN"
        logger.info(
            f"[SearchManager] {pname} entered cooldown for {secs}s "
            f"(until {int(until)}) | Breaker state is OPEN"
        )
        print(
            f"[SearchManager] {pname} entered cooldown for {secs}s. "
            f"Breaker is OPEN."
        )

    def _recover_cooled_providers(self) -> None:
        """Transition providers from OPEN to HALF_OPEN state once cooldown expires."""
        now = time.time()
        for pname, until in list(self._provider_cooldowns.items()):
            # Only transition if breaker is OPEN and cooldown has elapsed
            if self._provider_breaker_states.get(pname) == "OPEN" and now >= until:
                self.provider_health[pname] = True
                self._provider_breaker_states[pname] = "HALF_OPEN"
                del self._provider_cooldowns[pname]
                if pname == "bing":
                    self.bing_recovery_count += 1
                logger.info(f"[SearchManager] {pname} recovered from cooldown. Breaker is HALF_OPEN.")
                print(f"[SearchManager] {pname} recovered from cooldown. Breaker is HALF_OPEN (next request is a probe).")

    def _record_provider_failure_score(self, pname: str, points: float, reason: str) -> None:
        """Accumulate failure points for a provider and trip breaker if threshold exceeded."""
        state = self._provider_breaker_states.get(pname, "CLOSED")
        
        if state == "HALF_OPEN":
            # Any failure during HALF_OPEN immediately trips the breaker back to OPEN
            logger.warning(f"[SearchManager] {pname} failed probe query (Reason: {reason}). Tripping breaker back to OPEN.")
            print(f"[SearchManager] {pname} failed probe query (Reason: {reason}). Tripping breaker back to OPEN.")
            self._enter_cooldown(pname)
            return

        if state == "CLOSED":
            self._provider_failure_scores[pname] += points
            current_score = self._provider_failure_scores[pname]
            logger.info(f"[SearchManager] {pname} recorded {points} failure points (Reason: {reason}). Total: {current_score:.1f}/10.0")
            print(f"[SearchManager] {pname} recorded {points} failure points (Reason: {reason}). Total: {current_score:.1f}/10.0")
            
            if current_score >= 10.0:
                logger.warning(f"[SearchManager] {pname} failure score reached {current_score:.1f}. Tripping breaker to OPEN.")
                print(f"[SearchManager] {pname} failure score reached {current_score:.1f}. Tripping breaker to OPEN (cooldown active).")
                self._enter_cooldown(pname)

    def _track_source(self, url: str) -> None:
        """Track which domain a result came from for source ranking."""
        try:
            from urllib.parse import urlparse
            host = urlparse(url).netloc.lower().lstrip("www.")
            if host:
                self.source_breakdown[host] = self.source_breakdown.get(host, 0) + 1
        except Exception:
            pass

    # ── Statistics ────────────────────────────────────────────────────────────

    def print_stats(self) -> None:
        """Print a comprehensive formatted report: yield funnel, source ranking, timing, metrics."""
        div60 = "=" * 60
        div40 = "=" * 40

        print("\n" + div60)
        print("SEARCH LAYER STATISTICS")
        print(div60)
        print(f"  Total queries     : {self.total_queries}")
        print(f"  Total results     : {self.total_results}")
        print(f"  Duplicates removed: {self.total_duplicates_removed}")
        print(f"  Merged results    : {self.total_merged}")
        cache_stats = self.cache.get_stats()
        print(f"  Successful cache hits : {cache_stats.get('successful_hits', 0)}")
        print(f"  Zero-result cache hits: {cache_stats.get('zero_result_hits', 0)}")
        print(f"  Expired cache entries : {cache_stats.get('expired_entries', 0)}")
        print(f"  Cache bypasses        : {cache_stats.get('bypasses', 0)}")
        print(f"  Debug mode bypasses   : {cache_stats.get('debug_bypasses', 0)}")
        print(f"  Live executions       : {self.queries_live_run}")
        print()

        # ── Google summary ───────────────────────────────────────────
        g_success_rate = (self.google_successes / self.google_queries) if self.google_queries > 0 else 0.0
        print("  Google")
        print(f"    Queries          : {self.google_queries}")
        print(f"    Successes        : {self.google_successes}  ({g_success_rate:.0%})")
        print(f"    429 Rate Limits  : {self.google_429s}")
        print(f"    CAPTCHA pages    : {self.google_captchas}")
        print(f"    Parser failures  : {self.google_parser_fail_queries}")
        print(f"    EnableJS pages   : {self.google_enable_js_queries}")
        print(f"    Zero-result SERPs: {self.google_zero_result_queries}")
        print(f"    Fallbacks to next: {self.google_fallbacks}")
        print(f"    Retries (proxies): {self.google_retries}")
        print()

        # ── Circuit breaker ───────────────────────────────────────────
        try:
            from search.google_scheduler import GoogleRequestScheduler
            cb_stats = GoogleRequestScheduler().get_circuit_breaker_stats()
            print("  Google Circuit Breaker")
            print(f"    Times opened     : {cb_stats['total_opens']}")
            print(f"    Currently open   : {'YES' if cb_stats['circuit_open'] else 'No'}")
            print(f"    Window failures  : {cb_stats['window_failures']}/{cb_stats['window_size']}")
            print(f"    Failure ratio    : {cb_stats['failure_ratio']:.0%}")
        except Exception:
            pass
        print()

        # ── Bing summary ────────────────────────────────────────────
        print("  Bing")
        print(f"    Queries          : {self.bing_queries}")
        print(f"    Successes        : {self.bing_successes}")
        print(f"    Failures         : {self.bing_failures}")
        print(f"    Cooldown recoveries: {self.bing_recovery_count}")
        print()

        # ── Overall ───────────────────────────────────────────────
        total_attempts  = self.google_queries + self.bing_queries
        total_successes = self.google_successes + self.bing_successes
        overall_rate    = (total_successes / total_attempts) if total_attempts > 0 else 0.0
        print(f"  Overall success rate : {overall_rate:.0%}")
        print()

        # ── Search Yield Analysis ─────────────────────────────────────
        print(div60)
        print("SEARCH YIELD ANALYSIS")
        print(div60)
        print(f"  Queries generated  : {self.total_queries}")
        print(f"  Cache hits         : {self.cache_hits}  (prevented live calls)")
        print(f"  Queries live-run   : {self.queries_live_run}")
        print()
        print("  Live query outcomes:")
        live = self.queries_live_run or 1
        print(f"  - Valid results     : {self.google_successes + self.bing_successes}  ({(self.google_successes + self.bing_successes) / live:.0%})")
        print(f"  - Zero results      : {self.queries_zero_results}  ({self.queries_zero_results / live:.0%})")
        print(f"  - Parser failure    : {self.queries_parser_fail}  ({self.queries_parser_fail / live:.0%})")
        print(f"  - Google blocked    : {self.queries_google_blocked}  ({self.queries_google_blocked / live:.0%})")
        print(f"  - Bing blocked      : {self.queries_bing_blocked}  ({self.queries_bing_blocked / live:.0%})")
        print(f"  - Skipped (circuit) : {self.queries_skipped_circuit}")
        print()
        print("  Actionable savings:")
        print(f"  - Retries avoided by cache    : {self.cache_hits}")
        print(f"  - Duplicate queries prevented : {self.queries_deduplicated}")
        print()

        # ── Company Source Ranking ───────────────────────────────────
        if self.source_breakdown:
            print(div60)
            print("COMPANY SOURCE RANKING")
            print(div60)
            print(f"  {'Domain':<30} Results")
            print(f"  {'-'*30} -------")
            for domain, count in sorted(
                self.source_breakdown.items(), key=lambda x: x[1], reverse=True
            )[:15]:
                print(f"  {domain:<30} {count}")
            print()

        # ── Per-provider execution timing ──────────────────────────────
        print(div60)
        print("EXECUTION TIMING BREAKDOWN")
        print(div60)
        total_search_time = sum(s.total_latency_s for s in self.stats.values())
        for pname, pstats in self.stats.items():
            if pstats.queries > 0:
                avg_lat = pstats.total_latency_s / pstats.queries
                print(
                    f"  {pname:<20}: {pstats.total_latency_s:.1f}s total "
                    f"({pstats.queries} queries x {avg_lat:.1f}s avg)"
                )
        print(f"  {'Total search':<20}: {total_search_time:.1f}s")
        print()

        # ── Proxy statistics ───────────────────────────────────────────
        google_html_instance = self._instances.get("google_html")
        if google_html_instance and hasattr(google_html_instance, "_client"):
            pm = google_html_instance._client.proxy_manager
            with pm._lock:
                proxies = list(pm._proxies)
            if proxies:
                total_p = len(proxies)
                dead = sum(1 for p in proxies if p.dead)
                cooling = sum(1 for p in proxies if any(time.time() < ts for ts in p.cooldown_until.values()))
                google_blocked = sum(1 for p in proxies if not p.dead and p.google_status == "blocked")
                bing_only = sum(1 for p in proxies if not p.dead and p.bing_status == "healthy" and p.google_status == "blocked")
                healthy = sum(1 for p in proxies if not p.dead and not any(time.time() < ts for ts in p.cooldown_until.values()))
                avg_score = (sum(p.proxy_score for p in proxies) / total_p) if total_p > 0 else 0.0

                print(div40)
                print("PROXY STATISTICS")
                print(div40)
                print(f"  Loaded proxies    : {total_p}")
                print(f"  Healthy           : {healthy}")
                print(f"  Cooling down      : {cooling}")
                print(f"  Google blocked    : {google_blocked}")
                print(f"  Bing only         : {bing_only}")
                print(f"  Dead              : {dead}")
                print(f"  Average score     : {avg_score:.1f}")
                print()

                sorted_proxies = sorted(proxies, key=lambda p: p.proxy_score, reverse=True)
                print("  Top 10 proxies by score:")
                for p in sorted_proxies[:10]:
                    print(f"    {p.raw_url:<22}: score={p.proxy_score:.1f} (google={p.google_status}, bing={p.bing_status})")
                print()

        # ── Google parser report ────────────────────────────────────────
        avg_html_size = (
            sum(self.google_html_sizes) // len(self.google_html_sizes) // 1024
        ) if self.google_html_sizes else 0
        parser_denom = self.google_successful_serps + self.google_parser_failures
        parser_success_rate = (
            self.google_successful_serps / parser_denom
        ) if parser_denom > 0 else 0.0

        from search.google_parser_registry import GoogleParserRegistry
        registry_report = GoogleParserRegistry.get_report()
        total_parses   = sum(r["successes"] for r in registry_report.values())
        total_time_ms  = sum(r["successes"] * r["avg_time_ms"] for r in registry_report.values())
        avg_parse_time = (total_time_ms / total_parses) if total_parses > 0 else 0.0

        active_parsers = {k: v for k, v in registry_report.items() if (v["successes"] + v["failures"]) > 0}
        best_parser  = max(active_parsers, key=lambda k: active_parsers[k]["success_rate"]) if active_parsers else "N/A"
        worst_parser = min(active_parsers, key=lambda k: active_parsers[k]["success_rate"]) if active_parsers else "N/A"

        print(div40)
        print("GOOGLE PARSER REPORT")
        print(div40)
        print(f"  Requests sent        : {self.google_requests_sent}")
        print(f"  Successful parses    : {self.google_successful_serps}")
        print(f"  Parser failures      : {self.google_parser_failures}")
        print(f"  Consent pages        : {self.google_consent_pages}")
        print(f"  EnableJS pages       : {self.google_enablejs_pages}")
        print(f"  CAPTCHA pages        : {self.google_captchas}")
        print(f"  Unknown layouts      : {self.google_unknown_layouts}")
        print(f"  Average HTML size    : {avg_html_size} KB")
        print(f"  Average parse time   : {avg_parse_time:.0f} ms")
        print(f"  Best parser          : {best_parser}")
        print(f"  Worst parser         : {worst_parser}")
        print(f"  Parser success rate  : {parser_success_rate:.0%}")
        print()
        print("  Per-parser stats:")
        for name, r in registry_report.items():
            total_p = r["successes"] + r["failures"]
            if total_p > 0:
                print(f"    {name:<20}: {r['successes']:>3} ok / {r['failures']:>3} fail  ({r['success_rate']:.0%})  avg={r['avg_time_ms']:.0f}ms")
        print()

        # ── Provider health ───────────────────────────────────────────
        print("  Provider health (end of run):")
        for name, healthy in self.provider_health.items():
            cooldown_until = self._provider_cooldowns.get(name, 0)
            remaining = max(0, int(cooldown_until - time.time())) if cooldown_until else 0
            if healthy:
                status = "OK   (healthy)"
            elif remaining > 0:
                status = f"COOL (cooldown {remaining}s remaining)"
            else:
                status = "ERR  (unhealthy)"
            print(f"    {name:<20} {status}")
        print(div60)



    def diagnose(self) -> None:
        """
        Print a human-readable provider readiness report.

        Call this before running the pipeline to understand exactly which
        providers are ready and what config keys are needed for the others.

        Output example
        --------------
        PROVIDER READINESS CHECK
        ========================
          [READY]    bing          — always available (no key required)
          [NO KEY]   serpapi       — set SERPAPI_KEY in .env to enable
          [NO KEY]   google_cse    — set GOOGLE_CSE_KEY + GOOGLE_CSE_CX in .env
          [DISABLED] google_html   — set ENABLE_GOOGLE_HTML=True to enable
          [DISABLED] generic_api   — set ENABLE_CUSTOM_PROVIDER=True + CUSTOM_PROVIDER_URL
        """
        import config as _cfg

        print("\n" + "=" * 60)
        print("PROVIDER READINESS CHECK")
        print("=" * 60)
        print(f"  Mode     : {self._mode}")
        print(f"  Priority : {', '.join(self._priority)}")
        print()

        _HINTS = {
            "serpapi": (
                "SERPAPI_KEY",
                "set SERPAPI_KEY=<your_key> in .env  "
                "(get one free at https://serpapi.com)"
            ),
            "google_cse": (
                "GOOGLE_CSE_KEY + GOOGLE_CSE_CX",
                "set GOOGLE_CSE_KEY=<key> and GOOGLE_CSE_CX=<cx> in .env  "
                "(Google Custom Search JSON API)"
            ),
            "generic_api": (
                "ENABLE_CUSTOM_PROVIDER + CUSTOM_PROVIDER_URL",
                "set ENABLE_CUSTOM_PROVIDER=True and CUSTOM_PROVIDER_URL=<url> in .env"
            ),
            "google_html": (
                None,
                "primary provider — uses curl_cffi Chrome TLS impersonation (always available)"
            ),
            "bing": (
                None,
                "final fallback — always available, no key required"
            ),
        }

        ready_count = 0
        for name, cls in PROVIDER_REGISTRY.items():
            instance = self._get_instance(name)
            available = instance.is_available()
            caps      = instance.capabilities
            hint_key, hint_msg = _HINTS.get(name, (None, "see provider docs"))

            if available:
                status = "[READY]   "
                detail = "available"
                ready_count += 1
            else:
                # Figure out WHY it's not available
                enable_flag = f"ENABLE_{name.upper()}"
                flag_val    = getattr(_cfg, enable_flag, None)

                if flag_val is False:
                    status = "[DISABLED]"
                else:
                    status = "[NO KEY]  "
                detail = hint_msg

            in_priority = name in self._priority
            priority_tag = "" if in_priority else "  [not in priority list]"
            print(f"  {status} {name:<20} {detail}{priority_tag}")

        print()
        if ready_count == 0:
            print("  WARNING: No providers are ready.  Searches will return empty results.")
            print("  At minimum, Bing must be enabled (ENABLE_BING=True).")
        else:
            active = [
                name for name in self._priority
                if name in PROVIDER_REGISTRY and self._get_instance(name).is_available()
            ]
            print(f"  Active provider order: {' -> '.join(active) if active else 'none'}")
        print("=" * 60 + "\n")



    # ── Internal helpers ──────────────────────────────────────────────────────

    # Cost tiers: lower = cheaper.  Used to prevent paid providers from
    # outscoring free ones just by being reliable.
    PROVIDER_COST_TIER: dict[str, int] = {
        "google_html": 0,
        "duckduckgo": 0,
        "brave": 0,
        "bing": 0,
        "brightdata": 1,          # paid — rescue only
        "directory_provider": 0,
        "repository_provider": 0,
    }

    def _get_provider_score(self, name: str) -> float:
        stats = self.stats.get(name)
        if not stats or stats.queries == 0:
            return 100.0

        import math
        q = stats.queries
        # Lead Yield: 35%
        lead_yield = (stats.leads_discovered / q) * 100.0

        # Business Acceptance: 20%
        biz_acceptance = (stats.business_accepted / q) * 100.0

        # HTTP Success: 10%
        http_success = (stats.successful_queries / q) * 100.0

        # Latency: 25% — steeper penalty so a 15s provider is clearly worse than a 2s one.
        avg_latency = stats.avg_latency_s
        latency_score = max(0.0, 100.0 - avg_latency * 8.0)

        # Block Rate: 10%
        block_rate = (stats.failures / q) * 100.0
        safety_score = max(0.0, 100.0 - block_rate)

        # Blend: 35% Lead Yield + 20% Biz Accept + 10% HTTP Success + 25% Latency + 10% Block Rate
        base_score = (
            0.35 * lead_yield
            + 0.20 * biz_acceptance
            + 0.10 * http_success
            + 0.25 * latency_score
            + 0.10 * safety_score
        )

        # Floor score for low sample size to prevent early tanking
        if q < 3:
            base_score = max(20.0, base_score)

        # Exploration bonus
        exploration_bonus = 15.0 / math.sqrt(q)
        score = base_score + exploration_bonus

        # Cost penalty: paid providers get a deduction so they can't outscore
        # free providers through reliability alone.  A perfect BrightData run
        # scores ~80 instead of ~100, which is lower than a decently-performing
        # free provider.
        cost_tier = self.PROVIDER_COST_TIER.get(name, 0)
        if cost_tier > 0:
            score -= 20.0 * cost_tier

        return max(1.0, min(100.0, score))

    def get_adaptive_timeout(self, pname: str) -> float:
        stats = self.stats.get(pname)
        if not stats or not getattr(stats, "latencies", []):
            if "google" in pname.lower(): return 15.0
            if "directory" in pname.lower(): return 20.0
            if "repository" in pname.lower(): return 15.0
            return 15.0
            
        latencies = stats.latencies[-20:]
        n = len(latencies)
        mean = sum(latencies) / n
        
        if n < 2:
            std_dev = 0.0
        else:
            variance = sum((x - mean) ** 2 for x in latencies) / (n - 1)
            std_dev = variance ** 0.5
            
        timeout = mean + 2.0 * std_dev
        
        if "google" in pname.lower():
            return max(6.0, min(20.0, timeout))
        if "directory" in pname.lower():
            return max(8.0, min(30.0, timeout))
        if "repository" in pname.lower():
            timeout = max(5.0, min(20.0, timeout))
        else:
            timeout = max(6.0, min(20.0, timeout))

        if hasattr(self, "budget_manager"):
            remaining = self.budget_manager.remaining_provider_time(pname)
            timeout = min(timeout, max(1.0, remaining))

        return timeout

    def _get_ordered_providers(self) -> list[SearchProvider]:
        """
        Return provider instances in the order they should be tried.

        - Respects SEARCH_PROVIDER_PRIORITY
        - Dynamically sorts based on ProxyManager's numeric provider score
        - Filters out providers not in PROVIDER_REGISTRY
        - Filters out providers whose is_available() == False
        """
        ordered: list[SearchProvider] = []

        for name in self._priority:
            if not ProviderRegistry.get_provider_class(name):
                print(f"[SearchManager] Warning: unknown provider {name!r} in priority list")
                continue
            instance = self._get_instance(name)
            if not instance.is_available():
                print(f"[SearchManager] [{name}] not available (config/credentials check failed)")
                continue
            ordered.append(instance)

        if not ordered:
            print(
                "[SearchManager] Warning: no providers are available. "
                "Check config keys and ENABLE_* flags."
            )
            return ordered

        # ── Cost-tier-aware ordering ─────────────────────────────────────
        # Primary sort key: configured priority index (preserves the intended
        #   Google → DDG → Brave → Bing → BrightData ordering).
        # Secondary sort key: provider health score (breaks ties within the
        #   same priority rank — e.g. if Google is in cooldown, DDG moves up).
        #
        # This replaces the old unconstrained score-sort that let BrightData
        # jump to first place simply by succeeding, masking the health of
        # every free provider.
        priority_index = {name: idx for idx, name in enumerate(self._priority)}

        def _sort_key(p):
            idx = priority_index.get(p.name, 999)
            stats = self.stats.get(p.name)
            if stats and stats.queries > 0:
                success_rate = (stats.queries - stats.failures) / stats.queries
            else:
                success_rate = 1.0

            # Demote low success-rate providers (Health < 0.2)
            if success_rate < 0.2:
                idx += 10
            # Promote high success-rate free providers (Health > 0.8)
            elif success_rate > 0.8 and idx > 0 and self.PROVIDER_COST_TIER.get(p.name, 0) == 0:
                idx -= 1

            is_healthy = self.provider_health.get(p.name, True)
            breaker = self._provider_breaker_states.get(p.name, "CLOSED")
            if not is_healthy or breaker == "OPEN":
                idx += 100  # push to end
            return (idx, -success_rate)  # lower idx = higher priority; higher success_rate = better

        ordered.sort(key=_sort_key)

        # Epsilon-Greedy Exploration: 10% chance to swap two adjacent
        # *free-tier* providers (never promotes BrightData to first).
        import random
        if len(ordered) > 1 and random.random() < 0.10:
            free_providers = [
                i for i, p in enumerate(ordered)
                if self.PROVIDER_COST_TIER.get(p.name, 0) == 0
            ]
            if len(free_providers) > 1:
                explore_idx = random.choice(free_providers[1:])
                explored_provider = ordered.pop(explore_idx)
                ordered.insert(free_providers[0], explored_provider)
                print(f"[SearchManager] Epsilon-Greedy: Exploring provider {explored_provider.name!r} by moving it to the front of free tier.")

        return ordered

    def _get_instance(self, name: str) -> SearchProvider:
        """Return a cached provider instance, creating it on first use."""
        if name not in self._instances:
            cls = ProviderRegistry.get_provider_class(name)
            self._instances[name] = cls()
        return self._instances[name]


# ─────────────────────────────────────────────────────────────────────────────
# Global singleton + backward-compat shim
# ─────────────────────────────────────────────────────────────────────────────

_manager: SearchManager | None = None


def get_search_manager() -> SearchManager:
    """Return the global SearchManager singleton (created on first call)."""
    global _manager
    if _manager is None:
        _manager = SearchManager()
    return _manager


def run_search(
    query: str,
    max_results: int | None = None,
    start: int = 0,
    family: str = "unknown",
) -> list[dict]:
    """
    Backward-compatibility shim.

    discovery/company_discovery.py and contact_discovery.py call this
    function exactly as before.  It returns plain dicts (not SearchResult
    objects) so the rest of the pipeline doesn't need to change.

    Parameters
    ----------
    query       : Search query string
    max_results : Maximum results (defaults to config.MAX_RESULTS_PER_QUERY)
    start       : Result offset → converted to page index
    family      : The template family of this query
    """
    max_r  = max_results or getattr(config, "MAX_RESULTS_PER_QUERY", 10)
    page   = start // max_r if max_r else 0
    manager = get_search_manager()
    results = manager.search(query, max_results=max_r, page=page, family=family)
    return [r.to_dict() for r in results]
