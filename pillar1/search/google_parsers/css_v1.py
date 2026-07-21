"""
search/google_parsers/css_v1.py
================================
CSSParserV1 — Classic `div.g` block extractor.

Targets the traditional Google SERP layout where each organic result
is wrapped in a `div.g` container. Works on layouts from 2020–2023.
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

_SKIP_BLOCK_CLASSES = frozenset({
    "uEierd", "commercial-unit-desktop-top", "ads-ad",
    "related-question-pair", "g-blk", "ULSxyf", "nDgy9d",
    "ueGUFe", "sh-dlr__list-result", "g-inner-card",
    "X5OiLe", "RzdJxc", "iKFuM", "AJLUJb",
})


class CSSParserV1(BaseGoogleParser):
    """Classic div.g block parser — Google SERP 2020-2023 layout."""

    name = "CSSParserV1"

    def parse(
        self,
        html: str,
        max_results: int,
        query: str,
        page: int,
    ) -> List[SearchResult]:
        soup = BeautifulSoup(html, "html.parser")

        # Remove known ad/noise blocks
        for cls in _SKIP_BLOCK_CLASSES:
            for el in soup.select(f".{cls}"):
                el.decompose()
        for el in soup.select("g-section-with-header, .dDajDf, .commercial-unit-desktop-top"):
            el.decompose()

        results: List[SearchResult] = []
        ts = time.time()
        rank = 0

        for g in soup.select("div.g"):
            r = self._extract_block(g, query, page, ts)
            if r:
                rank += 1
                r.provider_rank = rank
                results.append(r)
                if len(results) >= max_results:
                    break

        return results

    def _extract_block(self, block, query: str, page: int, ts: float) -> SearchResult | None:
        if block.get("data-sokoban-container") or block.get("data-hveid") == "":
            return None
        a = block.select_one("a[href]")
        if not a:
            return None
        href = self._normalize_url(a.get("href"))
        if not href or self._is_skip_domain(href):
            return None
        h3 = a.select_one("h3")
        title = h3.get_text(" ", strip=True) if h3 else a.get_text(" ", strip=True)
        if not title:
            return None
        snip_el = block.select_one(
            "div.VwiC3b, div.yDqZbe, span.aCOpbc, div.hb85Bf, div.MU1Yt, "
            "span.MU1Yt, div.lEBKkf, div.IsZvec span, span.st"
        )
        snippet = snip_el.get_text(" ", strip=True) if snip_el else block.get_text(" ", strip=True).replace(title, "", 1).strip()
        return SearchResult(
            url=href, title=title,
            snippet=snippet[:400] if snippet else None,
            provider="google_html", source="Google",
            provider_rank=0, query=query, page=page, timestamp=ts,
        )

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
