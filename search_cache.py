import json
import os
import time
from typing import Any


class SearchCache:
    """Small on-disk cache for search results with zero-result protection."""

    def __init__(
        self,
        filename: str,
        ttl_seconds: int,
        enabled: bool,
        namespace: str = "default",
        zero_result_ttl: int = 1800,
        cache_zero_results: bool = False,
    ) -> None:
        self.filename = filename
        self.namespace = (namespace or "default").strip()
        self.ttl = ttl_seconds
        self.zero_result_ttl = zero_result_ttl
        self.enabled = enabled
        self.cache_zero_results = cache_zero_results
        self._cache: dict[str, dict[str, Any]] = {}
        self.stats = {
            "successful_hits": 0,
            "zero_result_hits": 0,
            "expired_entries": 0,
            "bypasses": 0,
            "debug_bypasses": 0,
        }
        if self.enabled and os.path.exists(self.filename):
            try:
                with open(self.filename, "r", encoding="utf-8") as handle:
                    self._cache = json.load(handle)
            except Exception as exc:
                print(f"[SearchCache] Error loading cache file {self.filename}: {exc}")

    def _get_key(self, query: str, max_results: int, page: int) -> str:
        return f"{self.namespace}||{query}||{max_results}||{page}"

    def _entry_ttl(self, entry: dict[str, Any]) -> int:
        if entry.get("kind") == "zero_result":
            return self.zero_result_ttl
        return self.ttl

    def get(self, query: str, max_results: int, page: int) -> list | None:
        if not self.enabled:
            self.stats["bypasses"] += 1
            return None

        key = self._get_key(query, max_results, page)
        entry = self._cache.get(key)
        if not entry:
            return None

        age = time.time() - entry.get("timestamp", 0.0)
        ttl = self._entry_ttl(entry)
        if age < ttl:
            if entry.get("kind") == "zero_result":
                self.stats["zero_result_hits"] += 1
            else:
                self.stats["successful_hits"] += 1
            return entry.get("results")

        self.stats["expired_entries"] += 1
        self._cache.pop(key, None)
        self.save()
        return None

    def set(
        self,
        query: str,
        max_results: int,
        page: int,
        provider_name: str,
        results: list,
        kind: str = "success",
    ) -> None:
        if not self.enabled:
            return

        if not results and kind == "success":
            if not self.cache_zero_results:
                return
            kind = "zero_result"

        if not results and kind != "zero_result":
            return

        key = self._get_key(query, max_results, page)
        self._cache[key] = {
            "query": query,
            "provider": provider_name,
            "timestamp": time.time(),
            "result_count": len(results),
            "kind": kind,
            "results": [r.to_dict() for r in results],
        }
        self.save()

    def save(self) -> None:
        if not self.enabled:
            return
        try:
            with open(self.filename, "w", encoding="utf-8") as handle:
                json.dump(self._cache, handle, indent=2, ensure_ascii=False)
        except Exception as exc:
            print(f"[SearchCache] Error saving cache: {exc}")

    def get_stats(self) -> dict[str, int]:
        return dict(self.stats)
