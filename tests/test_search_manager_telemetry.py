from __future__ import annotations

from search.exceptions import ProviderParseError
from search.manager import SearchManager


class _DummyCache:
    def get(self, query: str, max_results: int, page: int):
        return None

    def set(self, query: str, max_results: int, page: int, provider_name: str, results: list, kind: str = "success"):
        return None

    def get_stats(self) -> dict:
        return {
            "successful_hits": 0,
            "zero_result_hits": 0,
            "expired_entries": 0,
            "bypasses": 0,
            "debug_bypasses": 0,
        }


class _EmptyProvider:
    name = "bing"

    def is_available(self) -> bool:
        return True

    def search(self, query: str, max_results: int = 10, page: int = 0):
        return []


class _ParseFailureProvider:
    name = "bing"

    def is_available(self) -> bool:
        return True

    def search(self, query: str, max_results: int = 10, page: int = 0):
        raise ProviderParseError(self.name, "parse failed")


def test_search_manager_counts_zero_results_once(monkeypatch):
    import discovery.company_discovery as company_discovery

    manager = SearchManager()
    manager.cache = _DummyCache()
    monkeypatch.setattr(manager, "_get_ordered_providers", lambda: [_EmptyProvider()])
    monkeypatch.setattr(company_discovery, "classify_result", lambda result: ("COMPANY", None))
    monkeypatch.setattr(company_discovery, "should_ignore_result", lambda result: False)

    results = manager.search("python company", max_results=10)

    assert results == []
    assert manager.queries_zero_results == 1
    assert manager.stats["bing"].queries == 1
    assert manager.stats["bing"].successful_queries == 0


def test_search_manager_separates_parser_failures(monkeypatch):
    manager = SearchManager()
    manager.cache = _DummyCache()
    monkeypatch.setattr(manager, "_get_ordered_providers", lambda: [_ParseFailureProvider()])

    results = manager.search("python company", max_results=10)

    assert results == []
    assert manager.stats["bing"].parser_failures == 1
    assert manager.stats["bing"].failures == 0
    assert manager.queries_parser_fail == 1