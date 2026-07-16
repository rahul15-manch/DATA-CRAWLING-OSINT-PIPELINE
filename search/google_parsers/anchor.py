"""
search/google_parsers/anchor.py
================================
AnchorParser — Generic anchor fallback extractor.

Last-resort parser. Extracts any external anchor that isn't a skip domain.
Produces lower-quality results (no snippets) but is highly robust.
Only runs after all structured parsers have failed.
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


class AnchorParser(BaseGoogleParser):
    """Generic anchor fallback — returns any external link with a meaningful title."""

    name = "AnchorParser"

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
            title = a.get_text(" ", strip=True)
            if len(title) < 5:
                continue
            rank += 1
            results.append(SearchResult(
                url=href, title=title,
                snippet=None,
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
