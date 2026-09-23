"""
pillar1/query/retrieval_metrics.py
==================================
Calculates retrieval quality metrics and search intelligence telemetry.

Metrics tracked:
- Query yield: unique search results / executed queries
- Lead yield: unique qualified leads / executed queries
- Duplicate rate: duplicate results / total search results
- Domain diversity: unique domains / total search results
- Retrieval latency: phase execution duration via time.perf_counter()
"""

import time
from typing import Dict, Any, List
from urllib.parse import urlparse


class RetrievalMetricsTracker:
    """
    Computes and aggregates search retrieval quality metrics.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self.queries_generated = 0
        self.queries_executed = 0
        self.total_results = 0
        self.unique_results = set()
        self.unique_domains = set()
        self.unique_leads = set()
        self.start_time = None
        self.end_time = None

    def start_timing(self):
        self.start_time = time.perf_counter()

    def stop_timing(self):
        self.end_time = time.perf_counter()

    def record_query(self, query: str):
        self.queries_executed += 1

    def record_result(self, url: str):
        if not url:
            return
        self.total_results += 1
        norm_url = url.strip().rstrip("/").lower()
        self.unique_results.add(norm_url)
        try:
            domain = urlparse(norm_url).netloc.lower()
            if domain:
                if domain.startswith("www."):
                    domain = domain[4:]
                self.unique_domains.add(domain)
        except Exception:
            pass

    def record_lead(self, lead_id_or_name: str):
        if lead_id_or_name:
            self.unique_leads.add(str(lead_id_or_name).strip().lower())

    @property
    def latency_seconds(self) -> float:
        if self.start_time is None:
            return 0.0
        end = self.end_time if self.end_time is not None else time.perf_counter()
        return round(end - self.start_time, 4)

    @property
    def query_yield(self) -> float:
        """Unique results per executed query."""
        if self.queries_executed == 0:
            return 0.0
        return round(len(self.unique_results) / float(self.queries_executed), 3)

    @property
    def lead_yield(self) -> float:
        """Unique leads per executed query."""
        if self.queries_executed == 0:
            return 0.0
        return round(len(self.unique_leads) / float(self.queries_executed), 3)

    @property
    def duplicate_rate(self) -> float:
        """Duplicate results / total results."""
        if self.total_results == 0:
            return 0.0
        dupes = max(0, self.total_results - len(self.unique_results))
        return round(dupes / float(self.total_results), 3)

    @property
    def domain_diversity(self) -> float:
        """Unique domains / total results."""
        if self.total_results == 0:
            return 0.0
        return round(len(self.unique_domains) / float(self.total_results), 3)

    def summary(self) -> Dict[str, Any]:
        """Return structured metric dictionary."""
        return {
            "queries_executed": self.queries_executed,
            "total_results": self.total_results,
            "unique_results": len(self.unique_results),
            "unique_domains": len(self.unique_domains),
            "unique_leads": len(self.unique_leads),
            "query_yield": self.query_yield,
            "lead_yield": self.lead_yield,
            "duplicate_rate": self.duplicate_rate,
            "domain_diversity": self.domain_diversity,
            "latency_seconds": self.latency_seconds,
        }
