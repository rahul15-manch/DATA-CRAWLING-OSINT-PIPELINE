"""
search/google_parsers/semantic.py
===================================
SemanticParser — h3-inside-anchor semantic extraction.

Finds any anchor tag that directly contains an h3 element.
This is the semantic pattern Google uses for all organic results
regardless of the outer container class.
"""
from __future__ import annotations

import time
from typing import List
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from search.google_parsers.base import BaseGoogleParser
from search.result import SearchResult

_SKIP_DOMAINS = frozenset({
    "google.com", "google.co.in", "google.co.uk",
    "googleadservices.com", "doubleclick.net",
    "youtube.com", "maps.google.com",
    "support.google.com", "accounts.google.com",
})


class SemanticParser(BaseGoogleParser):
    """Semantic h3-in-anchor parser — layout-agnostic."""

    name = "SemanticParser"

    def parse(
        self,
        html: str,
        max_results: int,
        query: str,
        page: int,
    ) -> List[SearchResult]:
        soup = BeautifulSoup(html, "html.parser")
        results: List[SearchResult] = []
        ts = time.time()
        rank = 0

        for a in soup.select("a[href]"):
            href = self._normalize_url(a.get("href"))
            if not href or self._is_skip_domain(href) or href.startswith("/"):
                continue
            h3 = a.select_one("h3")
            if not h3:
                continue
            title = h3.get_text(" ", strip=True)
            if not title:
                continue
            parent = a.find_parent("div")
            snippet = parent.get_text(" ", strip=True).replace(title, "", 1).strip() if parent else ""
            rank += 1
            results.append(SearchResult(
                url=href, title=title,
                snippet=snippet[:400] if snippet else None,
                provider="google_html", source="Google",
                provider_rank=rank, query=query, page=page, timestamp=ts,
            ))
            if len(results) >= max_results:
                break

        return results

    def _normalize_url(self, href: str | None) -> str | None:
        if not href:
            return None
        href = href.strip()
        if href.startswith("/url?"):
            params = parse_qs(urlparse(href).query)
            if "q" in params:
                return params["q"][0]
        parsed = urlparse(href)
        if parsed.scheme in {"http", "https"}:
            return href
        return None

    def _is_skip_domain(self, url: str) -> bool:
        try:
            host = urlparse(url).netloc.lower().lstrip("www.")
            return any(host == d or host.endswith("." + d) for d in _SKIP_DOMAINS)
        except Exception:
            return False
