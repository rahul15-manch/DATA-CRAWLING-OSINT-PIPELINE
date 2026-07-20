from search_cache import SearchCache


def test_search_cache_namespace_isolation(tmp_path):
    cache_file = tmp_path / "search_cache.json"

    cache_a = SearchCache(str(cache_file), ttl_seconds=60, enabled=True, namespace="run_a")
    cache_b = SearchCache(str(cache_file), ttl_seconds=60, enabled=True, namespace="run_b")

    class _Result:
        def __init__(self, url: str):
            self.url = url

        def to_dict(self):
            return {
                "url": self.url,
                "title": "A",
                "snippet": "",
                "provider": "test",
                "source": "test",
                "rank": 1,
                "provider_rank": 1,
                "query": "python company",
                "page": 0,
                "timestamp": 0.0,
            }

    cache_a.set("python company", 10, 0, "test", [_Result("https://a.example")], kind="success")

    hit_a = cache_a.get("python company", 10, 0)
    hit_b = cache_b.get("python company", 10, 0)

    assert hit_a is not None
    assert hit_b is None
