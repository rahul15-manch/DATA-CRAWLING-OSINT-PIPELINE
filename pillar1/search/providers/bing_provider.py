"""
search/providers/bing_provider.py
==================================
Bing HTML scraper — the final, always-available fallback provider.
"""

from __future__ import annotations

import random
import time
import logging
from base64 import urlsafe_b64decode
from urllib.parse import parse_qs, quote_plus, urlparse

from bs4 import BeautifulSoup

import config
from pillar3_network_resilience.network.client import get_network_client
from search.exceptions import ProviderUnavailable, ProviderParseError
from search.provider_base import Capabilities, SearchProvider
from search.result import SearchResult
from search.search_validator import validate_search_response
from pillar3_network_resilience.network.middleware.base import Request

logger = logging.getLogger(__name__)

class BingProvider(SearchProvider):

    name = "bing"

    capabilities = Capabilities(
        supports_pagination  = True,
        supports_snippets    = True,
        supports_titles      = True,
        supports_rate_limit  = False,
        max_results_per_page = 10,
    )

    _SEARCH_URL = "https://www.bing.com/search?q={query}"

    def __init__(self, network_client=None):
        self._client = network_client or get_network_client()
        self._cookie_session_id = "bing:search"
        self._cooldown_until = 0.0
        self._backoff_index = 0

    def _next_backoff(self) -> int:
        sequence = [3, 6, 12, 24]
        step = min(self._backoff_index, len(sequence) - 1)
        self._backoff_index = min(self._backoff_index + 1, len(sequence) - 1)
        return sequence[step]

    def _reset_backoff(self) -> None:
        self._cooldown_until = 0.0
        self._backoff_index = 0

    def is_available(self) -> bool:
        return bool(getattr(config, "ENABLE_BING", True))

    def search(
        self,
        request_or_query: Request | str,
        max_results: int = 10,
        page: int = 0,
    ) -> list[SearchResult]:
        from search.search_validator import validate_search_response, SearchValidationResult

        if isinstance(request_or_query, Request):
            query = request_or_query.query or ""
            page = request_or_query.meta.get("page", 0)
            max_results = request_or_query.meta.get("max_results", 10)
        else:
            query = request_or_query

        if not self.is_available():
            raise ProviderUnavailable(self.name, "ENABLE_BING is False")

        if time.time() < self._cooldown_until:
            remaining = int(self._cooldown_until - time.time())
            raise ProviderUnavailable(self.name, f"Bing cooling down for {remaining}s after anti-bot response")

        url = self._SEARCH_URL.format(query=quote_plus(query))
        if page > 0:
            url += f"&first={page * max_results + 1}"

        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Cache-Control": "no-cache",
            "Referer": "https://www.bing.com/",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Upgrade-Insecure-Requests": "1",
        }

        # Stable session per query
        q_session_id = f"bing:{abs(hash(query)) % 10000}"

        for attempt in range(1, 3):
            from utils.deadline import Deadline
            if attempt > 1 and Deadline.is_exceeded():
                logger.warning("[BingProvider] Global deadline exceeded. Aborting Bing search retries.")
                break
            # Pre-request delay to prevent aggressive bot flagging
            if attempt == 1:
                time.sleep(random.uniform(1.5, 3.5))
            
            html = ""
            status_code = 200
            url_actual = url
            results = []

            try:
                # ProxyMiddleware handles direct_first policy via provider tag
                print(f"[BingProvider] Attempt {attempt}/2")
                resp = self._client.get(
                    url,
                    session_id=q_session_id,
                    headers=headers,
                    auto_score=False,
                    provider="bing",
                    timeout=15.0,
                )
                status_code = resp.status_code
                url_actual = resp.url
                html = resp.text
                results = self._parse(html, max_results, query, page)
                val_result = validate_search_response("bing", html, status_code, url_actual, results)
            except Exception as exc:
                val_result = SearchValidationResult(
                    status="NETWORK_FAILURE",
                    result_count=0,
                    classification="NETWORK_ERROR",
                    failure_reason=str(exc)
                )

            print(f"[BingProvider] Attempt {attempt}/2 - Request validation status: {val_result.status}")

            # Update scoring exactly once per attempt
            proxy = self._client.proxy_manager._sticky_sessions.get("bing")
            if proxy:
                if val_result.status in ["VALID_RESULTS", "VALID_ZERO_RESULTS"]:
                    proxy.record_success(domain="www.bing.com", reason=val_result.status)
                else:
                    proxy.record_failure(domain="www.bing.com", reason=val_result.status)

            if val_result.status in ["VALID_RESULTS", "VALID_ZERO_RESULTS"]:
                self._reset_backoff()
                return results

            if val_result.status in ["CAPTCHA", "RATE_LIMIT"]:
                if attempt < 2:
                    # Rotate session and retry once quickly
                    time.sleep(random.uniform(2.5, 4.5))
                    continue
                else:
                    # Final attempt failed, now we cooldown
                    wait_for = self._next_backoff()
                    self._cooldown_until = time.time() + wait_for

            if attempt == 2 or val_result.status == "CONSENT_PAGE":
                # Bubble exceptions/errors cleanly on final attempt
                if val_result.status == "CAPTCHA":
                    raise ProviderUnavailable(self.name, val_result.failure_reason or "Bing CAPTCHA detected")
                elif val_result.status == "RATE_LIMIT":
                    raise ProviderUnavailable(self.name, val_result.failure_reason or "Bing rate-limited")
                elif val_result.status == "CONSENT_PAGE":
                    raise ProviderUnavailable(self.name, val_result.failure_reason or "Bing cookie consent page redirect")
                elif val_result.status == "PARSER_FAILURE":
                    raise ProviderParseError(self.name, val_result.failure_reason or "Bing parse failure")
                elif val_result.status == "UNKNOWN_LAYOUT":
                    raise ProviderParseError(self.name, val_result.failure_reason or "Bing unknown HTML layout signature")
                else: # NETWORK_FAILURE / RATE_LIMIT
                    raise ProviderUnavailable(self.name, val_result.failure_reason or "Bing request failed")

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

        # Bing often A/B tests its DOM layout. We handle multiple variants.
        elements = soup.select("li.b_algo, div.b_algo, .b_algo")
        
        for rank, result in enumerate(elements, start=1):
            title_link = result.select_one("h2 a, .b_title h2 a")
            if not title_link:
                continue

            url = self._normalize_url(title_link.get("href"))
            if not url:
                continue

            snippet_el = result.select_one(".b_caption p, .b_paractl, p")
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
