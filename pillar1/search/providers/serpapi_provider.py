"""
search/providers/serpapi_provider.py
=====================================
SerpAPI provider — uses the official SerpAPI REST endpoint.

Config keys
-----------
SERPAPI_KEY           : API key (required, read from os.getenv or config)
ENABLE_SERPAPI        : bool flag (default True)
MAX_RESULTS_PER_QUERY : max results per call (default 10)

Failover behaviour
------------------
- Missing key      → ProviderUnavailable at is_available() time
- HTTP 429 / quota → ProviderUnavailable raised from search()
- Network error    → ProviderUnavailable raised from search()
- Any other error  → ProviderUnavailable raised from search()

Connection
----------
Direct HTTP connection via requests with timeout and direct routing
(bypasses rotating proxy pool to prevent proxy failure cascading).
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any

import requests

import config
from search.exceptions import ProviderParseError, ProviderUnavailable
from search.provider_base import Capabilities, SearchProvider
from search.result import SearchResult
from network_client_project.network.middleware.base import Request

logger = logging.getLogger(__name__)


class SerpApiProvider(SearchProvider):

    name = "serpapi"

    capabilities = Capabilities(
        supports_pagination  = True,
        supports_snippets    = True,
        supports_titles      = True,
        supports_rate_limit  = True,   # SerpAPI has a monthly quota
        max_results_per_page = 10,
    )

    _BASE_URL = "https://serpapi.com/search.json"

    def __init__(self, session: requests.Session | None = None, **kwargs: Any):
        # Direct HTTP session (bypasses local rotating proxy pool)
        self._session = session or requests.Session()
        self._session.trust_env = False

    @staticmethod
    def _log_outcome(outcome: str, message: str) -> None:
        log_line = f"[SERPAPI] {outcome}: {message}"
        if outcome in ("SUCCESS", "EMPTY"):
            logger.info(log_line)
            print(log_line)
        else:
            logger.warning(log_line)
            print(log_line)

    @staticmethod
    def _safe_error_detail(exc: Exception | str, api_key: str) -> str:
        """Redact API credentials echoed by HTTP client exception URLs."""
        detail = str(exc)
        if api_key:
            detail = detail.replace(api_key, "[REDACTED]")
        return re.sub(r"(api_key=)[^&\s)]+", r"\1[REDACTED]", detail, flags=re.I)

    # ── Availability ──────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        api_key = os.getenv("SERPAPI_KEY") or getattr(config, "SERPAPI_KEY", "")
        return bool(
            getattr(config, "ENABLE_SERPAPI", True)
            and api_key
        )

    # ── Search ────────────────────────────────────────────────────────────────

    def search(
        self,
        request_or_query: Request | str,
        max_results: int = 10,
        page: int = 0,
        deadline = None,
    ) -> list[SearchResult]:
        if isinstance(request_or_query, Request):
            query = request_or_query.query or ""
            page = request_or_query.meta.get("page", 0)
            max_results = request_or_query.meta.get("max_results", 10)
        else:
            query = request_or_query

        req_timeout = 15.0
        if deadline:
            rem = deadline.remaining()
            if rem <= 0.0 or deadline.is_exceeded():
                from utils.deadline import DeadlineExceeded
                raise DeadlineExceeded("SerpAPI deadline budget exhausted")
            req_timeout = min(req_timeout, max(1.0, rem))

        api_key = os.getenv("SERPAPI_KEY") or getattr(config, "SERPAPI_KEY", "")
        if not (getattr(config, "ENABLE_SERPAPI", True) and api_key):
            self._log_outcome("AUTH_ERROR", "SERPAPI_KEY not set or ENABLE_SERPAPI=False")
            raise ProviderUnavailable(self.name, "SERPAPI_KEY not set or ENABLE_SERPAPI=False")

        num_results = min(max_results, self.capabilities.max_results_per_page)
        params: dict[str, Any] = {
            "q":       query,
            "num":     num_results,
            "api_key": api_key,
            "engine":  "google",
        }
        if page > 0:
            params["start"] = page * max_results

        try:
            resp = self._session.get(self._BASE_URL, params=params, timeout=req_timeout)
        except requests.exceptions.Timeout as exc:
            detail = self._safe_error_detail(exc, api_key)
            self._log_outcome("TIMEOUT", f"Request timed out after {req_timeout:.1f}s for query='{query}'")
            raise ProviderUnavailable(self.name, f"SerpAPI request timed out: {detail}") from exc
        except requests.exceptions.RequestException as exc:
            detail = self._safe_error_detail(exc, api_key)
            self._log_outcome("NETWORK_ERROR", f"Network error: {detail}")
            raise ProviderUnavailable(self.name, f"SerpAPI network error: {detail}") from exc
        except Exception as exc:
            detail = self._safe_error_detail(exc, api_key)
            self._log_outcome("NETWORK_ERROR", f"Unexpected error: {detail}")
            raise ProviderUnavailable(self.name, f"SerpAPI request failed: {detail}") from exc

        if resp.status_code == 401:
            self._log_outcome("AUTH_ERROR", "HTTP 401 - Invalid or expired SERPAPI_KEY")
            raise ProviderUnavailable(self.name, "invalid or expired SERPAPI_KEY (HTTP 401)")

        if resp.status_code == 429:
            self._log_outcome("RATE_LIMITED", "HTTP 429 - Quota exceeded or rate limited")
            raise ProviderUnavailable(self.name, "quota exceeded (HTTP 429)")

        if not resp.ok:
            self._log_outcome("NETWORK_ERROR", f"HTTP {resp.status_code}")
            raise ProviderUnavailable(self.name, f"HTTP {resp.status_code}")

        try:
            data = resp.json()
        except Exception as exc:
            self._log_outcome("PARSER_ERROR", f"Failed to parse JSON: {exc}")
            raise ProviderParseError(self.name, f"invalid JSON response: {exc}") from exc

        # SerpAPI returns an error field when something goes wrong
        if "error" in data:
            err_msg = str(data["error"])
            err_lower = err_msg.lower()
            if any(k in err_lower for k in ("quota", "credit", "rate limit", "exceeded", "plan")):
                self._log_outcome("RATE_LIMITED", f"Quota/rate limit in response: {err_msg}")
                raise ProviderUnavailable(self.name, f"quota exceeded: {err_msg}")
            elif any(k in err_lower for k in ("api key", "unauthorized", "auth", "invalid key", "forbidden")):
                self._log_outcome("AUTH_ERROR", f"Auth error in response: {err_msg}")
                raise ProviderUnavailable(self.name, f"invalid API key: {err_msg}")
            else:
                self._log_outcome("NETWORK_ERROR", f"SerpAPI error: {err_msg}")
                raise ProviderUnavailable(self.name, f"SerpAPI error: {err_msg}")

        organic = data.get("organic_results", [])
        if not isinstance(organic, list):
            self._log_outcome("PARSER_ERROR", "organic_results field is not a list")
            raise ProviderParseError(self.name, "invalid organic_results structure in SerpAPI response")

        results: list[SearchResult] = []
        ts = time.time()

        for rank, item in enumerate(organic[:max_results], start=1):
            url = item.get("link") or ""
            if not url:
                continue
            results.append(
                SearchResult(
                    url           = url,
                    title         = item.get("title"),
                    snippet       = item.get("snippet"),
                    provider      = self.name,
                    source        = "Google",
                    provider_rank = rank,
                    query         = query,
                    page          = page,
                    timestamp     = ts,
                )
            )

        if not results:
            self._log_outcome("EMPTY", f"0 results returned for query='{query}'")
        else:
            self._log_outcome("SUCCESS", f"{len(results)} results returned for query='{query}'")

        return results
