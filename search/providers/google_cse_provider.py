"""
search/providers/google_cse_provider.py
========================================
Google Custom Search Engine (CSE) provider.

Uses the official Google Custom Search JSON API.
Documentation: https://developers.google.com/custom-search/v1/reference/rest/v1/cse/list

Config keys
-----------
GOOGLE_CSE_KEY    : Google API key  (required)
GOOGLE_CSE_CX     : Custom Search Engine ID  (required)
ENABLE_GOOGLE_CSE : bool flag (default True)

How to get credentials
-----------------------
1. Go to https://console.cloud.google.com/
2. Create a project → enable "Custom Search API"
3. Create an API key  → set as GOOGLE_CSE_KEY
4. Go to https://programmablesearchengine.google.com/
5. Create a search engine → copy the Search Engine ID → set as GOOGLE_CSE_CX

Failover behaviour
------------------
- Missing key/cx        → ProviderUnavailable at is_available() time
- HTTP 429 / 403 quota  → ProviderUnavailable
- Network error         → ProviderUnavailable

Pagination note
---------------
Google CSE uses a 1-based `start` param (not 0-based).
page 0 → start=1, page 1 → start=11, etc.

NetworkClient
-------------
Uses the project's NetworkClient for consistent retry, proxy, and UA handling.
"""

from __future__ import annotations

import time

import config
from network_client_project.network import NetworkClient
from network_client_project.network.exceptions import NetworkClientError
from search.exceptions import ProviderUnavailable
from search.provider_base import Capabilities, SearchProvider
from search.result import SearchResult


class GoogleCseProvider(SearchProvider):

    name = "google_cse"

    capabilities = Capabilities(
        supports_pagination  = True,
        supports_snippets    = True,
        supports_titles      = True,
        supports_rate_limit  = True,    # 100 free queries/day; paid beyond
        max_results_per_page = 10,      # Google CSE hard limit per call
    )

    _BASE_URL = "https://www.googleapis.com/customsearch/v1"

    def __init__(self, network_client: NetworkClient | None = None):
        self._client = network_client or NetworkClient()

    # ── Availability ──────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        return bool(
            getattr(config, "ENABLE_GOOGLE_CSE", True)
            and getattr(config, "GOOGLE_CSE_KEY", "")
            and getattr(config, "GOOGLE_CSE_CX", "")
        )

    # ── Search ────────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        max_results: int = 10,
        page: int = 0,
    ) -> list[SearchResult]:

        if not self.is_available():
            raise ProviderUnavailable(
                self.name,
                "GOOGLE_CSE_KEY or GOOGLE_CSE_CX not set, or ENABLE_GOOGLE_CSE=False",
            )

        # CSE uses 1-based start index; each page = 10 results
        start = page * 10 + 1

        params: dict = {
            "key":   config.GOOGLE_CSE_KEY,
            "cx":    config.GOOGLE_CSE_CX,
            "q":     query,
            "num":   min(max_results, 10),  # CSE hard max is 10
            "start": start,
        }

        try:
            resp = self._client.get(self._BASE_URL, params=params)
        except NetworkClientError as exc:
            raise ProviderUnavailable(self.name, f"network error: {exc}") from exc
        except Exception as exc:
            exc_str = str(exc).lower()
            if "401" in exc_str or "403" in exc_str:
                raise ProviderUnavailable(
                    self.name,
                    "auth/permission error — check GOOGLE_CSE_KEY and GOOGLE_CSE_CX",
                ) from exc
            if "429" in exc_str:
                raise ProviderUnavailable(self.name, "quota exceeded (HTTP 429)") from exc
            raise ProviderUnavailable(self.name, f"request failed: {exc}") from exc

        if resp.status_code in (429, 403):
            raise ProviderUnavailable(
                self.name,
                f"quota or permission error (HTTP {resp.status_code}) — "
                "check your Google Cloud Console for quota usage",
            )

        if resp.status_code == 400:
            raise ProviderUnavailable(
                self.name,
                "HTTP 400 — check that GOOGLE_CSE_CX is correct",
            )

        if not resp.ok:
            raise ProviderUnavailable(self.name, f"HTTP {resp.status_code}")

        try:
            data = resp.json()
        except ValueError as exc:
            raise ProviderUnavailable(self.name, f"invalid JSON response: {exc}") from exc

        # Google CSE surfaces errors in the response body
        if "error" in data:
            err = data["error"]
            raise ProviderUnavailable(
                self.name,
                f"Google API error {err.get('code')}: {err.get('message')}",
            )

        items = data.get("items", [])
        results: list[SearchResult] = []
        ts = time.time()

        for rank, item in enumerate(items[:max_results], start=1):
            url = item.get("link") or ""
            if not url:
                continue
            results.append(
                SearchResult(
                    url           = url,
                    title         = item.get("title"),
                    snippet       = item.get("snippet"),
                    provider      = self.name,
                    source        = "Google CSE",
                    provider_rank = rank,
                    query         = query,
                    page          = page,
                    timestamp     = ts,
                )
            )

        return results
