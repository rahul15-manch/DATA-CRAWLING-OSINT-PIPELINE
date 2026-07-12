"""
search/providers/google_html_provider.py
=========================================
Google HTML Provider — PRIMARY search provider.

Uses curl_cffi Chrome TLS impersonation via NetworkClient.
No API key required.

Design
------
- No hardcoded headers (NetworkClient.get() already generates perfect
  browser-matching headers via HeaderManager + curl_cffi).
- Availability: always available (no ENABLE flag required).
- Failover: on parse failure → tries next provider (ProviderParseError),
  NOT permanently blacklisted so it retries on the next query.
- Parser: multi-strategy, skips ads / PAA / carousels / news / shopping.
- LinkedIn dorks work naturally — just pass "site:linkedin.com/company keyword"
  as the query from the query generator.

Debug
-----
When zero organic results are parsed, raw HTML is saved to
`google_debug_last_zero.html` for offline inspection.
"""

from __future__ import annotations

import time
from urllib.parse import parse_qs, quote_plus, urlparse

from bs4 import BeautifulSoup

from network_client_project.network import NetworkClient
from search.exceptions import ProviderParseError, ProviderUnavailable
from search.provider_base import Capabilities, SearchProvider
from search.result import SearchResult

# ─── Domains / URL patterns that are never organic results ────────────────────
_SKIP_DOMAINS = frozenset({
    "google.com", "google.co.in", "google.co.uk",
    "googleadservices.com", "doubleclick.net",
    "youtube.com",                  # video results
    "maps.google.com",              # maps
    "support.google.com",           # support pages
    "accounts.google.com",
})

# CSS classes that Google uses for non-organic blocks — skip entirely
_SKIP_BLOCK_CLASSES = frozenset({
    # Ads
    "uEierd",   # top-of-page ad container
    "commercial-unit-desktop-top",
    "ads-ad",
    # People Also Ask
    "related-question-pair",
    "g-blk",
    # News carousel
    "ULSxyf",
    "nDgy9d",
    # Top stories
    "ueGUFe",
    # Shopping
    "sh-dlr__list-result",
    "g-inner-card",
    # Videos
    "X5OiLe",
    "RzdJxc",
    # Related searches
    "iKFuM",
    "AJLUJb",
})


class GoogleHtmlProvider(SearchProvider):

    name = "google_html"

    capabilities = Capabilities(
        supports_pagination  = True,
        supports_snippets    = True,
        supports_titles      = True,
        supports_rate_limit  = True,
        max_results_per_page = 10,
    )

    _SEARCH_URL = "https://www.google.com/search"

    # Browser-like headers to avoid immediate 403 / enablejs
    _HEADERS = {
        "User-Agent":               "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept":                   "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language":          "en-US,en;q=0.9",
        "Referer":                  "https://www.google.com/",
        "Connection":               "keep-alive",
        "Upgrade-Insecure-Requests":"1",
        "Sec-Ch-Ua":                '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "Sec-Ch-Ua-Mobile":         "?0",
        "Sec-Ch-Ua-Platform":       '"Windows"',
        "Sec-Fetch-Dest":           "document",
        "Sec-Fetch-Mode":           "navigate",
        "Sec-Fetch-Site":           "none",
        "Sec-Fetch-User":           "?1",
    }

    def __init__(self, network_client: NetworkClient | None = None):
        self._client = network_client or NetworkClient()

    # ── Availability ──────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Always available — uses curl_cffi Chrome impersonation, no API key."""
        return True

    # ── Search ────────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        max_results: int = 10,
        page: int = 0,
    ) -> list[SearchResult]:

        params = f"q={quote_plus(query)}&num={min(max_results, 10)}&hl=en&gl=us"
        if page > 0:
            params += f"&start={page * min(max_results, 10)}"
        url = f"{self._SEARCH_URL}?{params}"

        try:
            # NetworkClient handles UA rotation, TLS impersonation, rate limiting, retries
            resp = self._client.get(url, session_id="google_html")
            resp.raise_for_status()
        except Exception as exc:
            raise ProviderUnavailable(self.name, f"request failed: {exc}") from exc

        html      = resp.text
        html_size = len(html)

        # Detect blocking / anti-bot pages
        is_consent  = "consent.google.com" in html or "Before you continue" in html
        is_anti_bot = any(k in html for k in ("unusual traffic", "recaptcha", "captcha-form"))
        is_js_redir = "/httpservice/retry/enablejs" in html

        if is_consent or is_anti_bot or is_js_redir:
            if is_consent:
                reason = "Google Consent Page intercepted"
            elif is_anti_bot:
                reason = "Google Anti-Bot / CAPTCHA intercepted"
            else:
                reason = "Google JS-redirection (enablejs) enforcer"
            print(f"[GoogleHtmlProvider] Blocked: {reason}")
            self._save_debug_html(html)
            raise ProviderUnavailable(self.name, reason)

        results = self._parse(html, max_results, query, page)

        print(
            f"[GoogleHtmlProvider] HTML: {html_size:,} bytes"
            f" | parsed: {len(results)} organic results"
        )

        if not results:
            reason = "Parser: no organic result elements matched"
            print(f"[GoogleHtmlProvider] Zero results — {reason}")
            self._save_debug_html(html)
            # ProviderParseError = try next provider but DON'T blacklist permanently
            raise ProviderParseError(self.name, reason)

        return results

    # ── Parser (multi-strategy, ad/carousel-aware) ────────────────────────────

    def _parse(
        self,
        html: str,
        max_results: int,
        query: str,
        page: int,
    ) -> list[SearchResult]:
        soup = BeautifulSoup(html, "html.parser")

        # Remove known non-organic sections from the tree before walking it
        for cls in _SKIP_BLOCK_CLASSES:
            for el in soup.select(f".{cls}"):
                el.decompose()

        # Also remove <g-section-with-header> (news, videos, related)
        for el in soup.select("g-section-with-header, .dDajDf, .commercial-unit-desktop-top"):
            el.decompose()

        results: list[SearchResult] = []
        ts   = time.time()
        rank = 0

        # ── Strategy A: standard div.g blocks ────────────────────────────────
        g_blocks = soup.select("div.g")
        if g_blocks:
            for g in g_blocks:
                r = self._extract_from_block(g, query, page, ts)
                if r:
                    rank += 1
                    r.provider_rank = rank
                    results.append(r)
                    if len(results) >= max_results:
                        return results

        # ── Strategy B: div.yuRUbf anchor blocks ─────────────────────────────
        if not results:
            y_blocks = soup.select("div.yuRUbf")
            for y in y_blocks:
                a = y.select_one("a[href]")
                if not a:
                    continue
                href = self._normalize_url(a.get("href"))
                if not href or self._is_skip_domain(href):
                    continue
                h3      = a.select_one("h3")
                title   = h3.get_text(" ", strip=True) if h3 else a.get_text(" ", strip=True)
                snippet = ""
                parent  = y.find_parent("div", class_="g")
                if parent:
                    snip_el = parent.select_one("div.VwiC3b, div.yDqZbe, span.aCOpbc")
                    if snip_el:
                        snippet = snip_el.get_text(" ", strip=True)
                rank += 1
                results.append(SearchResult(
                    url=href, title=title or None,
                    snippet=snippet[:400] if snippet else None,
                    provider=self.name, source="Google",
                    provider_rank=rank, query=query, page=page, timestamp=ts,
                ))
                if len(results) >= max_results:
                    return results

        # ── Strategy C: link-centric fallback ────────────────────────────────
        if not results:
            for a in soup.select("a[href]"):
                href = self._normalize_url(a.get("href"))
                if not href or self._is_skip_domain(href) or href.startswith("/"):
                    continue
                h3 = a.select_one("h3")
                if not h3:
                    continue
                title   = h3.get_text(" ", strip=True)
                parent  = a.find_parent("div")
                snippet = (
                    parent.get_text(" ", strip=True).replace(title, "", 1).strip()
                    if parent else ""
                )
                rank += 1
                results.append(SearchResult(
                    url=href, title=title or None,
                    snippet=snippet[:400] if snippet else None,
                    provider=self.name, source="Google",
                    provider_rank=rank, query=query, page=page, timestamp=ts,
                ))
                if len(results) >= max_results:
                    break

        return results

    # ── Block extractor ───────────────────────────────────────────────────────

    def _extract_from_block(
        self,
        block,
        query: str,
        page: int,
        ts: float,
    ) -> SearchResult | None:
        """Extract a single organic result from a div.g block. Returns None if block is an ad."""
        # Skip blocks with data-hveid that indicate ads
        if block.get("data-sokoban-container") or block.get("data-hveid") == "":
            return None

        a = block.select_one("a[href]")
        if not a:
            return None

        href = self._normalize_url(a.get("href"))
        if not href or self._is_skip_domain(href):
            return None

        h3      = a.select_one("h3")
        title   = h3.get_text(" ", strip=True) if h3 else a.get_text(" ", strip=True)
        if not title:
            return None

        snip_el = block.select_one(
            "div.VwiC3b, div.yDqZbe, span.aCOpbc, div.hb85Bf, div.MU1Yt, span.MU1Yt, div.lEBKkf"
        )
        snippet = (
            snip_el.get_text(" ", strip=True)
            if snip_el
            else block.get_text(" ", strip=True).replace(title, "", 1).strip()
        )

        return SearchResult(
            url=href,
            title=title,
            snippet=snippet[:400] if snippet else None,
            provider=self.name,
            source="Google",
            provider_rank=0,   # will be set by caller
            query=query,
            page=page,
            timestamp=ts,
        )

    # ── URL helpers ───────────────────────────────────────────────────────────

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

    # ── Debug helpers ─────────────────────────────────────────────────────────

    def _save_debug_html(self, html: str) -> None:
        try:
            with open("google_debug_last_zero.html", "w", encoding="utf-8") as fh:
                fh.write(html)
            print("[GoogleHtmlProvider] Saved raw HTML -> google_debug_last_zero.html")
        except OSError as exc:
            print(f"[GoogleHtmlProvider] Could not save debug HTML: {exc}")
