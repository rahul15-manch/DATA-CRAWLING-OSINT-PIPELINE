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


def print_report() -> None:
    """Print a formatted pipeline statistics report."""
    s = get()

    lines = [
        "",
        "=" * 52,
        "  PIPELINE STATISTICS",
        "=" * 52,
        f"  Queries Generated    : {s.get('queries_generated', 0)}",
        f"  Queries Executed     : {s.get('queries_executed', 0)}",
        f"  Search Results       : {s.get('search_results', 0)}",
        f"  Rejected Results     : {s.get('rejected_results', 0)}",
        f"  Duplicate Companies  : {s.get('duplicate_companies', 0)}",
        f"  Validated Companies  : {s.get('validated_companies', 0)}",
        f"  Companies Crawled    : {s.get('companies_crawled', 0)}",
        f"  Lead Cards Generated : {s.get('lead_cards_generated', 0)}",
        f"  Avg Confidence Score : {s.get('avg_confidence', 0.0):.1f}",
        f"  Execution Time       : {s.get('execution_time_sec', 0.0):.2f}s",
        "=" * 52,
        "",
    ]
    print("\n".join(lines))


# Initialise on import so counters are always available
reset()
