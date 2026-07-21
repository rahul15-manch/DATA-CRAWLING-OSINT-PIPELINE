"""
search/google_parser_registry.py
==================================
Registry for all Google SERP parsers.

Maintains:
- PARSER_REGISTRY: ordered list of BaseGoogleParser instances (fixed order)
- Per-parser success/failure statistics
- A get_parsers() method returning the ordered instance list

Adding a new parser
-------------------
1. Create search/google_parsers/my_parser.py (subclass BaseGoogleParser)
2. Import and add an instance to PARSER_REGISTRY below
That's it — google_html_provider.py will pick it up automatically.
"""
import time
import threading
from typing import List, Dict

from search.google_parsers.css_v1 import CSSParserV1
from search.google_parsers.css_v2 import CSSParserV2
from search.google_parsers.xpath_parser import XPathParser
from search.google_parsers.semantic import SemanticParser
from search.google_parsers.json_ld import JsonLdParser
from search.google_parsers.anchor import AnchorParser
from search.google_parsers.base import BaseGoogleParser

# ── Fixed execution order — do NOT reorder automatically ──────────────────────
# Rationale: predictable order makes debugging far easier.
# Statistics are collected but do NOT change execution order.
PARSER_REGISTRY: List[BaseGoogleParser] = [
    CSSParserV1(),    # Classic div.g blocks (2020-2023)
    CSSParserV2(),    # Modern 2024 selectors
    XPathParser(),    # div.yuRUbf inner link-container
    SemanticParser(), # h3-in-anchor (layout agnostic)
    JsonLdParser(),   # JSON-LD ItemList schema
    AnchorParser(),   # Generic anchor fallback (last resort)
]


class GoogleParserRegistry:
    """
    Manages the parser execution list and tracks per-parser statistics.
    Statistics are informational only — execution order is fixed.
    """

    _lock = threading.Lock()

    # Stats keyed by parser.name
    stats: Dict[str, dict] = {
        p.name: {
            "successes": 0,
            "failures": 0,
            "total_time_ms": 0.0,
            "last_success": 0.0,
        }
        for p in PARSER_REGISTRY
    }

    @classmethod
    def get_parsers(cls) -> List[BaseGoogleParser]:
        """Return the ordered parser instance list (fixed order)."""
        return list(PARSER_REGISTRY)

    @classmethod
    def record_success(cls, parser_name: str, elapsed_ms: float) -> None:
        """Record a successful parse run."""
        with cls._lock:
            if parser_name in cls.stats:
                cls.stats[parser_name]["successes"] += 1
                cls.stats[parser_name]["total_time_ms"] += elapsed_ms
                cls.stats[parser_name]["last_success"] = time.time()

    @classmethod
    def record_failure(cls, parser_name: str) -> None:
        """Record a parser failure."""
        with cls._lock:
            if parser_name in cls.stats:
                cls.stats[parser_name]["failures"] += 1

    @classmethod
    def get_report(cls) -> dict:
        """Return summary statistics for all parsers."""
        with cls._lock:
            report = {}
            for name, data in cls.stats.items():
                total = data["successes"] + data["failures"]
                rate = (data["successes"] / total) if total > 0 else 0.0
                avg_time = (
                    data["total_time_ms"] / data["successes"]
                ) if data["successes"] > 0 else 0.0
                report[name] = {
                    "successes": data["successes"],
                    "failures": data["failures"],
                    "success_rate": rate,
                    "avg_time_ms": avg_time,
                    "last_success": data["last_success"],
                }
            return report
