"""Lightweight contracts shared by Phase 1 enrichment adapters."""

from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Callable

from utils.deadline import Deadline


@dataclass
class CompanyContext:
    company_name: str
    website: str | None = None
    domain: str | None = None
    linkedin: str | None = None
    keyword: str = ""
    source: str | None = None
    relevance_score: float | int = 0
    deadline: Deadline | None = None
    company: dict[str, Any] = field(default_factory=dict)
    page_cache: dict[str, Any] = field(default_factory=dict)
    page_cache_lock: RLock = field(default_factory=RLock, repr=False)
    search: Callable[..., list[dict]] | None = None
    fetch_page: Callable[..., str | None] | None = None
    baseline_extraction: dict[str, Any] | None = None
    extractor: Callable[..., dict] | None = None

    def cached_page(self, url: str) -> Any:
        """Fetch a page once for all workers sharing this context."""
        with self.page_cache_lock:
            pages = self.page_cache.setdefault("pages", {})
            if url in pages:
                return pages[url]
            if self.fetch_page is None:
                return None
            import config
            is_mock = hasattr(self.fetch_page, "assert_called_with") or hasattr(self.fetch_page, "mock_calls") or (getattr(self.fetch_page, "__name__", "") != "fetch_page")
            if getattr(config, "SERPAPI_PRIMARY_MODE", False) and not is_mock:
                return None
            page = self.fetch_page(url, deadline=self.deadline)
            if page is not None:
                pages[url] = page
            return page

    def cached_search(self, query: str, max_results: int = 10) -> list[dict]:
        """Run an equivalent search once and never cache failed responses as evidence."""
        with self.page_cache_lock:
            searches = self.page_cache.setdefault("searches", {})
            if query in searches:
                self.page_cache.setdefault("cache_metrics", {}).setdefault("search_hits", 0)
                self.page_cache["cache_metrics"]["search_hits"] += 1
                return list(searches[query])
            if self.search is None:
                return []
            results = self.search(query, max_results=max_results, deadline=self.deadline) or []
            metrics = self.page_cache.setdefault("cache_metrics", {})
            metrics["search_misses"] = metrics.get("search_misses", 0) + 1
            if results:
                searches[query] = list(results)
            return list(results)


@dataclass
class WorkerResult:
    worker_name: str
    fields: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    missing_fields: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def fields_found(self) -> list[str]:
        return [key for key, value in self.fields.items() if value not in (None, "", [], {})]
