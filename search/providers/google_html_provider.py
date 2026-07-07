"""
search/providers/google_html_provider.py
=========================================
Google HTML scraper — EXPERIMENTAL, disabled by default.

Why disabled by default
-----------------------
Google actively blocks HTML scrapers with JS-redirect enforcers
(/httpservice/retry/enablejs), consent pages, and CAPTCHA.
This provider should only be enabled when explicitly opted in via:

    ENABLE_GOOGLE_HTML=True

It is NOT included in the default provider priority list.

Config keys
-----------
ENABLE_GOOGLE_HTML : bool flag (default False)

Debug output
------------
When zero results are parsed, the raw HTML is saved to
`google_debug_last_zero.html` for offline inspection.
"""

from __future__ import annotations

import time
from urllib.parse import parse_qs, quote_plus, urlparse

from bs4 import BeautifulSoup

import config
from network_client_project.network import NetworkClient
from search.exceptions import ProviderUnavailable, ProviderParseError
from search.provider_base import Capabilities, SearchProvider
from search.result import SearchResult


class GoogleHtmlProvider(SearchProvider):

    name = "google_html"

    capabilities = Capabilities(
        supports_pagination  = True,
        supports_snippets    = True,
        supports_titles      = True,
        supports_rate_limit  = True,   # Google blocks scrapers aggressively
        max_results_per_page = 10,
    )

    _SEARCH_URL = "https://www.google.com/search?q={query}"

    # Browser-like headers to avoid immediate 403
    _HEADERS = {
        "User-Agent":               "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept":                   "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language":          "en-US,en;q=0.9",
        "Referer":                  "https://www.google.com/",
        "Connection":               "keep-alive",
        "Upgrade-Insecure-Requests":"1",
        "Sec-Ch-Ua":                '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        "Sec-Ch-Ua-Mobile":         "?0",
        "Sec-Ch-Ua-Platform":       '"Windows"',
        "Sec-Fetch-Dest":           "document",
        "Sec-Fetch-Mode":           "navigate",
        "Sec-Fetch-Site":           "cross-site",
        "Sec-Fetch-User":           "?1",
    }

    def __init__(self, network_client: NetworkClient | None = None):
        self._client = network_client or NetworkClient()

    # ── Availability ──────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Only available when explicitly enabled — experimental."""
        return bool(getattr(config, "ENABLE_GOOGLE_HTML", False))

    # ── Search ────────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        max_results: int = 10,
        page: int = 0,
    ) -> list[SearchResult]:

        if not self.is_available():
            raise ProviderUnavailable(
                self.name, "ENABLE_GOOGLE_HTML is False (experimental — opt-in required)"
            )

        url = self._SEARCH_URL.format(query=quote_plus(query))
        if page > 0:
            url += f"&start={page * max_results}"

        try:
            resp = self._client.get(url, headers=self._HEADERS)
            resp.raise_for_status()
        except Exception as exc:
            raise ProviderUnavailable(self.name, f"request failed: {exc}") from exc

        html      = resp.text
        html_size = len(html)

        # Detect blocking / anti-bot pages
        is_consent   = "consent.google.com" in html or "Before you continue" in html
        is_anti_bot  = any(k in html for k in ("unusual traffic", "captcha", "recaptcha", "captcha-form"))
        is_js_redir  = "/httpservice/retry/enablejs" in html

        results = self._parse(html, max_results, query, page)

        print(f"[GoogleHtmlProvider] HTML size: {html_size} bytes | parsed: {len(results)}")

        if not results:
            if is_consent:
                reason = "Google Consent Page intercepted"
            elif is_anti_bot:
                reason = "Google Anti-Bot / CAPTCHA intercepted"
            elif is_js_redir:
                reason = "Google JS-redirection (enablejs) enforcer"
            else:
                reason = "Parser failure (no organic result elements matched)"

            print(f"[GoogleHtmlProvider] Zero results. Reason: {reason}")

            # Save debug HTML
            try:
                with open("google_debug_last_zero.html", "w", encoding="utf-8") as fh:
                    fh.write(html)
                print("[GoogleHtmlProvider] Saved raw HTML → google_debug_last_zero.html")
            except OSError as exc:
                print(f"[GoogleHtmlProvider] Could not save debug HTML: {exc}")

            raise ProviderParseError(self.name, reason)

        return results

    # ── Parser (multi-strategy) ───────────────────────────────────────────────

    def _parse(
        self,
        html: str,
        max_results: int,
        query: str,
        page: int,
    ) -> list[SearchResult]:
        soup = BeautifulSoup(html, "html.parser")

        g_blocks = soup.select("div.g")
        y_blocks = soup.select("div.yuRUbf")
        t_blocks = soup.select("div.tF23ub")

        print(
            f"[GoogleHtmlProvider] Candidate blocks:"
            f" div.g={len(g_blocks)}"
            f" div.yuRUbf={len(y_blocks)}"
            f" div.tF23ub={len(t_blocks)}"
        )

        results: list[SearchResult] = []
        ts = time.time()
        rank = 0

        # Strategy A — standard div.g / div.tF23ub blocks
        blocks = g_blocks or t_blocks
        if blocks:
            for g in blocks:
                a = g.select_one("a[href]")
                if not a:
                    continue
                href = self._normalize_url(a.get("href"))
                if not href or "google.com" in href:
                    continue

                h3      = a.select_one("h3")
                title   = h3.get_text(" ", strip=True) if h3 else a.get_text(" ", strip=True)
                snip_el = g.select_one(
                    "div.VwiC3b, div.yDqZbe, span.aCOpbc, div.hb85Bf, div.MU1Yt, span.MU1Yt"
                )
                snippet = (
                    snip_el.get_text(" ", strip=True)
                    if snip_el
                    else g.get_text(" ", strip=True).replace(title, "", 1).strip()
                )
                rank += 1
                results.append(SearchResult(
                    url=href, title=title or None,
                    snippet=snippet[:400] if snippet else None,
                    provider=self.name, source="Google",
                    provider_rank=rank, query=query, page=page, timestamp=ts,
                ))
                if len(results) >= max_results:
                    return results

        # Strategy B — yuRUbf blocks
        if not results and y_blocks:
            for y in y_blocks:
                a = y.select_one("a[href]")
                if not a:
                    continue
                href = self._normalize_url(a.get("href"))
                if not href or "google.com" in href:
                    continue

                h3    = a.select_one("h3")
                title = h3.get_text(" ", strip=True) if h3 else a.get_text(" ", strip=True)
                snippet = ""
                parent_g = y.find_parent("div", class_="g")
                if parent_g:
                    snip_el = parent_g.select_one(
                        "div.VwiC3b, div.yDqZbe, span.aCOpbc, div.hb85Bf"
                    )
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

        # Strategy C — link-centric fallback
        if not results:
            for a in soup.select("a[href]"):
                href = self._normalize_url(a.get("href"))
                if not href or "google.com" in href or href.startswith("/"):
                    continue
                h3 = a.select_one("h3")
                if not h3:
                    continue
                title  = h3.get_text(" ", strip=True)
                parent = a.find_parent("div")
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
