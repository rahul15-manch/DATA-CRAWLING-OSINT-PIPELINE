"""
utils/stats_tracker.py
=======================
Thread-safe pipeline statistics tracker (Task 12).

Usage
-----
    import utils.stats_tracker as stats

    stats.reset()
    stats.increment("queries_executed")
    stats.increment("search_results", 12)
    stats.set_value("execution_time", 4.7)
    stats.print_report()
"""

import threading

_lock = threading.Lock()

_DEFAULT: dict = {
    "queries_generated":   0,
    "queries_executed":    0,
    "search_results":      0,
    "rejected_results":    0,
    "duplicate_companies": 0,
    "validated_companies": 0,
    "companies_crawled":   0,
    "lead_cards_generated": 0,
    "avg_confidence":      0.0,
    "execution_time_sec":  0.0,
    
    # Funnel Metrics
    "funnel_requests_sent":       0,
    "funnel_http_success":        0,
    "funnel_parser_success":      0,
    "funnel_business_candidates": 0,
    "funnel_business_accepted":   0,
    "funnel_homepage_crawled":    0,
    "funnel_contacts_extracted":  0,
    "funnel_leads_exported":      0,
    "cache_served_queries":       0,
    "zero_result_serps":          0,
}

_stats: dict = {}


def reset() -> None:
    """Clear all counters and reset to defaults."""
    with _lock:
        _stats.clear()
        _stats.update(_DEFAULT)


def increment(key: str, n: int = 1) -> None:
    """Atomically add n to the named counter."""
    with _lock:
        _stats[key] = _stats.get(key, 0) + n


def set_value(key: str, value) -> None:
    """Set an absolute value for a stat."""
    with _lock:
        _stats[key] = value


def get() -> dict:
    """Return a snapshot of the current stats."""
    with _lock:
        return dict(_stats)


# Note: Telemetry funnel printing has been moved to stats/dashboard.py
# to ensure a single source of truth reading from ProviderStatsTracker.

# Initialise on import so counters are always available
reset()
