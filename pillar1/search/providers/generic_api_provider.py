"""
search/providers/generic_api_provider.py
=========================================
Generic REST API provider — plug any JSON search API into Flowiz without
touching SearchManager or any other module.

Why "generic_api" not "custom"
-------------------------------
"custom" is ambiguous.  "generic_api" tells developers exactly what this
provider does: it speaks to a generic REST endpoint over HTTP.

Config keys
-----------
CUSTOM_PROVIDER_URL  : Base URL of the REST API endpoint (required)
CUSTOM_PROVIDER_KEY  : API key / Bearer token (optional — some APIs are open)
ENABLE_CUSTOM_PROVIDER: bool flag (default False — must opt-in)

Adapting to a new API
---------------------
Override `_parse_response()` in a subclass.  That single method is the
only thing that needs to change when Flowiz switches to a different API.
The rest of the provider (auth, HTTP, error handling) stays identical.

Example custom API response formats supported out of the box
------------------------------------------------------------
1. {"results": [{"title": ..., "url": ..., "description": ...}]}
2. {"organic_results": [{"title": ..., "link": ..., "snippet": ...}]}
3. {"hits": [{"title": ..., "url": ..., "body": ...}]}
4. [{"title": ..., "url": ..., "snippet": ...}]   ← flat list

For any other format, subclass and override `_parse_response`.
"""

from __future__ import annotations

import time
from typing import Any

import config
from pillar3_network_resilience.network import NetworkClient
from pillar3_network_resilience.network.exceptions import NetworkClientError
from search.exceptions import ProviderUnavailable
from search.provider_base import Capabilities, SearchProvider
from search.result import SearchResult
from pillar3_network_resilience.network.middleware.base import Request


class GenericApiProvider(SearchProvider):

    name = "generic_api"

    capabilities = Capabilities(
        supports_pagination  = True,
        supports_snippets    = True,
        supports_titles      = True,
        supports_rate_limit  = True,   # Assume API has rate limits
        max_results_per_page = 10,
    )

    def __init__(self, network_client: NetworkClient | None = None):
        self._client = network_client or NetworkClient()

    # ── Availability ──────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        return bool(
            getattr(config, "ENABLE_CUSTOM_PROVIDER", False)
            and getattr(config, "CUSTOM_PROVIDER_URL", "")
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
            raise ProviderUnavailable(
                self.name,
                "CUSTOM_PROVIDER_URL not set or ENABLE_CUSTOM_PROVIDER=False",
            )

        headers = self._build_headers()
        params  = self._build_params(query, max_results, page)

        try:
            resp = self._client.get(
                config.CUSTOM_PROVIDER_URL,
                headers=headers,
                params=params,
            )
        except NetworkClientError as exc:
            raise ProviderUnavailable(self.name, f"network error: {exc}") from exc
        except Exception as exc:
            raise ProviderUnavailable(self.name, f"request failed: {exc}") from exc

        if resp.status_code in (401, 403):
            raise ProviderUnavailable(self.name, f"auth error (HTTP {resp.status_code})")

        if resp.status_code == 429:
            raise ProviderUnavailable(self.name, "quota exceeded (HTTP 429)")

        if not resp.ok:
            raise ProviderUnavailable(self.name, f"HTTP {resp.status_code}")

        try:
            data = resp.json()
        except ValueError as exc:
            raise ProviderUnavailable(self.name, f"invalid JSON: {exc}") from exc

        return self._parse_response(data, query, page, max_results)


    # ── Overridable helpers ───────────────────────────────────────────────────

    def _build_headers(self) -> dict:
        """Build request headers. Override to add custom auth schemes."""
        headers: dict = {"Accept": "application/json"}
        key = getattr(config, "CUSTOM_PROVIDER_KEY", "")
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def _build_params(self, query: str, max_results: int, page: int) -> dict:
        """
        Build query parameters.  Override for APIs that use non-standard
        parameter names (e.g. `q` vs `query`, `limit` vs `num`).
        """
        return {
            "q":      query,
            "num":    max_results,
            "page":   page,
        }

    def _parse_response(
        self,
        data: Any,
        query: str,
        page: int,
        max_results: int,
    ) -> list[SearchResult]:
        """
        Parse the API response into SearchResult objects.

        Supports four common response shapes out of the box.
        Override this method to handle any other API structure.
        """
        # Detect response shape
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            # Try common key names in priority order
            for key in ("results", "organic_results", "hits", "data", "items"):
                if key in data and isinstance(data[key], list):
                    items = data[key]
                    break
            else:
                items = []
        else:
            items = []

        results: list[SearchResult] = []
        ts = time.time()

        for rank, item in enumerate(items[:max_results], start=1):
            if not isinstance(item, dict):
                continue

            # Try common URL field names
            url = (
                item.get("url")
                or item.get("link")
                or item.get("href")
                or item.get("uri")
                or ""
            )
            if not url:
                continue

            # Try common title field names
            title = (
                item.get("title")
                or item.get("name")
                or item.get("heading")
            )

            # Try common snippet field names
            snippet = (
                item.get("snippet")
                or item.get("description")
                or item.get("body")
                or item.get("summary")
                or item.get("extract")
            )

            results.append(
                SearchResult(
                    url           = url,
                    title         = title,
                    snippet       = str(snippet)[:400] if snippet else None,
                    provider      = self.name,
                    source        = "Generic API",
                    provider_rank = rank,
                    query         = query,
                    page          = page,
                    timestamp     = ts,
                )
            )

        return results
