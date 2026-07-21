"""
search/google_parsers/xpath_parser.py
=======================================
XPathParser — Extracts results via div.yuRUbf structured elements.

Falls back to this when div.g blocks are absent or empty.
Targets the `div.yuRUbf` which is Google's inner link-container.
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


class XPathParser(BaseGoogleParser):
    """div.yuRUbf extractor — Google inner link-container approach."""

    name = "XPathParser"

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

        for y in soup.select("div.yuRUbf"):
            a = y.select_one("a[href]")
            if not a:
                continue
            href = self._normalize_url(a.get("href"))
            if not href or self._is_skip_domain(href):
                continue
            h3 = a.select_one("h3")
            title = h3.get_text(" ", strip=True) if h3 else a.get_text(" ", strip=True)
            snippet = ""
            parent = y.find_parent("div", class_="g")
            if parent:
                snip_el = parent.select_one(
                    "div.VwiC3b, div.yDqZbe, span.aCOpbc, div.IsZvec span"
                )
                if snip_el:
                    snippet = snip_el.get_text(" ", strip=True)
            rank += 1
            results.append(SearchResult(
                url=href, title=title or None,
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
