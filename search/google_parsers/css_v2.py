"""
search/google_parsers/css_v2.py
================================
CSSParserV2 — Modern Google SERP extractor (2024+ layout).

Targets newer Google layouts that use:
- div[data-hveid]  — hveid-attributed result containers
- div.tF2Cxc       — 2024 result wrapper
- div.N54PNb       — nested result blocks
- div.kb0PBd       — alternate result container
- div.Ww4FFb       — another 2024 variant
- div.MjjYud       — mobile/unified SERP block
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

# Ordered by likelihood of containing organic results in 2024
_MODERN_SELECTORS = [
    "div.tF2Cxc",    # 2024 primary result wrapper
    "div.N54PNb",    # nested result block
    "div.kb0PBd",    # alternate container
    "div.Ww4FFb",    # another 2024 variant
    "div.MjjYud",    # mobile/unified SERP block
]


class CSSParserV2(BaseGoogleParser):
    """Modern Google SERP parser — 2024 layout selectors."""

    name = "CSSParserV2"

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
        seen_urls: set = set()
        rank = 0

        for selector in _MODERN_SELECTORS:
            for block in soup.select(selector):
                # Find the primary h3-bearing anchor (organic result link)
                anchor = None
                for a in block.select("a[href]"):
                    if a.select_one("h3"):
                        anchor = a
                        break
                if not anchor:
                    anchor = block.select_one("a[href]")
                if not anchor:
                    continue

                href = self._normalize_url(anchor.get("href"))
                if not href or self._is_skip_domain(href) or href in seen_urls:
                    continue

                h3 = anchor.select_one("h3") or block.select_one("h3")
                title = h3.get_text(" ", strip=True) if h3 else anchor.get_text(" ", strip=True)
                if not title or len(title) < 3:
                    continue

                snip_el = block.select_one(
                    "div.VwiC3b, div.yDqZbe, span.aCOpbc, "
                    "div.IsZvec span, div.hb85Bf, span.st, div.lEBKkf"
                )
                snippet = snip_el.get_text(" ", strip=True) if snip_el else None

                seen_urls.add(href)
                rank += 1
                results.append(SearchResult(
                    url=href, title=title,
                    snippet=snippet[:400] if snippet else None,
                    provider="google_html", source="Google",
                    provider_rank=rank, query=query, page=page, timestamp=ts,
                ))
                if len(results) >= max_results:
                    return results

            if results:
                # One selector was successful — stop trying others
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
