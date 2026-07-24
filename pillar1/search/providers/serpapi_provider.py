"""
search/providers/serpapi_provider.py
=====================================
SerpAPI provider — uses the official SerpAPI REST endpoint.

Config keys
-----------
SERPAPI_KEY           : API key (required)
ENABLE_SERPAPI        : bool flag (default True)
MAX_RESULTS_PER_QUERY : max results per call (default 10)

Failover behaviour
------------------
- Missing key      → ProviderUnavailable at is_available() time
- HTTP 429 / quota → ProviderUnavailable raised from search()
- Network error    → ProviderUnavailable raised from search()
- Any other error  → ProviderUnavailable raised from search()

NetworkClient
-------------
Uses the project's NetworkClient (not bare requests) so that retry logic,
proxy rotation, rate-limiting, and UA management are all active.
"""

from __future__ import annotations

import time

import config
from pillar3.network import NetworkClient
from pillar3.network.exceptions import NetworkClientError
from search.exceptions import ProviderUnavailable
from search.provider_base import Capabilities, SearchProvider
from search.result import SearchResult
from pillar3.network.middleware.base import Request


class SerpApiProvider(SearchProvider):

    name = "serpapi"

    capabilities = Capabilities(
        supports_pagination  = True,
        supports_snippets    = True,
        supports_titles      = True,
        supports_rate_limit  = True,   # SerpAPI has a monthly quota
        max_results_per_page = 10,
    )

    _BASE_URL = "https://serpapi.com/search.json"

    def __init__(self, network_client: NetworkClient | None = None):
        self._client = network_client or NetworkClient()

    # ── Availability ──────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        return bool(
            getattr(config, "ENABLE_SERPAPI", True)
            and getattr(config, "SERPAPI_KEY", "")
        )

    # ── Search ────────────────────────────────────────────────────────────────

    def search(
        self,
        request_or_query: Request | str,
        max_results: int = 10,
        page: int = 0,
    ) -> list[SearchResult]:
        if isinstance(request_or_query, Request):
            query = request_or_query.query or ""
            page = request_or_query.meta.get("page", 0)
            max_results = request_or_query.meta.get("max_results", 10)
        else:
            query = request_or_query

        if not self.is_available():
            raise ProviderUnavailable(self.name, "SERPAPI_KEY not set or ENABLE_SERPAPI=False")

        params: dict = {
            "q":       query,
            "num":     min(max_results, self.capabilities.max_results_per_page),
            "api_key": config.SERPAPI_KEY,
            "engine":  "google",          # default; SerpAPI also supports bing, etc.
        }
        if page > 0:
            params["start"] = page * max_results

        try:
            resp = self._client.get(self._BASE_URL, params=params)
        except NetworkClientError as exc:
            raise ProviderUnavailable(self.name, f"network error: {exc}") from exc
        except Exception as exc:
            # NetworkClient's retry engine raises a RetryError wrapping the
            # original HTTPError when all retries are exhausted.
            # Translate auth/quota failures into ProviderUnavailable immediately
            # so SearchManager can fail over without waiting for all retries.
            exc_str = str(exc).lower()
            if "401" in exc_str:
                raise ProviderUnavailable(
                    self.name,
                    "invalid or expired SERPAPI_KEY (HTTP 401) — "
                    "check your key at https://serpapi.com/manage-api-key",
                ) from exc
            if "429" in exc_str:
                raise ProviderUnavailable(self.name, "quota exceeded (HTTP 429)") from exc
            raise ProviderUnavailable(self.name, f"request failed: {exc}") from exc

        if resp.status_code == 429:
            raise ProviderUnavailable(self.name, "quota exceeded (HTTP 429)")

        if resp.status_code == 401:
            raise ProviderUnavailable(self.name, "invalid API key (HTTP 401)")

        if not resp.ok:
            raise ProviderUnavailable(self.name, f"HTTP {resp.status_code}")

        try:
            data = resp.json()
        except ValueError as exc:
            raise ProviderUnavailable(self.name, f"invalid JSON response: {exc}") from exc

        # SerpAPI returns an error field when something goes wrong
        if "error" in data:
            raise ProviderUnavailable(self.name, f"SerpAPI error: {data['error']}")

        organic = data.get("organic_results", [])
        results: list[SearchResult] = []
        ts = time.time()

        for rank, item in enumerate(organic[:max_results], start=1):
            url = item.get("link") or ""
            if not url:
                continue
            results.append(
                SearchResult(
                    url           = url,
                    title         = item.get("title"),
                    snippet       = item.get("snippet"),
                    provider      = self.name,
                    source        = "Google",      # SerpAPI wraps Google by default
                    provider_rank = rank,
                    query         = query,
                    page          = page,
                    timestamp     = ts,
                )
            )

        return results
