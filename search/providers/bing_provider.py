"""
search/providers/bing_provider.py
==================================
Bing HTML scraper — the final, always-available fallback provider.

This is a port of the original BingHtmlProvider from discovery/search_backend.py
into the new provider architecture.

Config keys
-----------
ENABLE_BING : bool flag (default True).  Set to False only in testing.

Notes
-----
- No API key required.
- Bing uses a 1-based `first` parameter for pagination.
- URL decoding handles Bing's base64-encoded redirect hrefs.
"""

from __future__ import annotations

import time
from base64 import urlsafe_b64decode
from urllib.parse import parse_qs, quote_plus, urlparse

from bs4 import BeautifulSoup

import config
from network_client_project.network import NetworkClient
from search.exceptions import ProviderUnavailable
from search.provider_base import Capabilities, SearchProvider
from search.result import SearchResult


class BingProvider(SearchProvider):

    name = "bing"

    capabilities = Capabilities(
        supports_pagination  = True,
        supports_snippets    = True,
        supports_titles      = True,
        supports_rate_limit  = False,  # No quota; HTML scraper
        max_results_per_page = 10,
    )

    _SEARCH_URL = "https://www.bing.com/search?q={query}"

    def __init__(self, network_client: NetworkClient | None = None):
        self._client = network_client or NetworkClient()

    # ── Availability ──────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        return bool(getattr(config, "ENABLE_BING", True))

    # ── Search ────────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        max_results: int = 10,
        page: int = 0,
    ) -> list[SearchResult]:

        if not self.is_available():
            raise ProviderUnavailable(self.name, "ENABLE_BING is False")

        url = self._SEARCH_URL.format(query=quote_plus(query))
        if page > 0:
            url += f"&first={page * max_results + 1}"

        try:
            resp = self._client.get(url, headers={"Accept-Encoding": "identity"})
            resp.raise_for_status()
        except Exception as exc:
            raise ProviderUnavailable(self.name, f"request failed: {exc}") from exc

        results = self._parse(resp.text, max_results, query, page)
        return results

    # ── Parser ────────────────────────────────────────────────────────────────

    def _parse(
        self,
        html: str,
        max_results: int,
        query: str,
        page: int,
    ) -> list[SearchResult]:
        soup = BeautifulSoup(html, "html.parser")
        results: list[SearchResult] = []
        ts = time.time()

        for rank, result in enumerate(soup.select("li.b_algo"), start=1):
            title_link = result.select_one("h2 a")
            if not title_link:
                continue

            url = self._normalize_url(title_link.get("href"))
            if not url:
                continue

            snippet_el = result.select_one(".b_caption p, p")
            title   = title_link.get_text(" ", strip=True) or None
            snippet = snippet_el.get_text(" ", strip=True) if snippet_el else None

            results.append(
                SearchResult(
                    url           = url,
                    title         = title,
                    snippet       = snippet,
                    provider      = self.name,
                    source        = "Bing",
                    provider_rank = rank,
                    query         = query,
                    page          = page,
                    timestamp     = ts,
                )
            )

            if len(results) >= max_results:
                break

        return results

    # ── URL helpers ───────────────────────────────────────────────────────────

    def _normalize_url(self, href: str | None) -> str | None:
        if not href:
            return None

        parsed        = urlparse(href)
        query_params  = parse_qs(parsed.query)
        encoded_url   = query_params.get("u", [None])[0]

        if encoded_url:
            if encoded_url.startswith("a1"):
                encoded_url = encoded_url[2:]
            padding = "=" * (-len(encoded_url) % 4)
            try:
                return urlsafe_b64decode(encoded_url + padding).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                pass

        if parsed.scheme in {"http", "https"}:
            return href

        return None
