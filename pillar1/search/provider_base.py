"""
search/provider_base.py
========================
Abstract base class that every search provider must implement.

Provider Contract
-----------------
1. Declare a unique `name` slug (e.g. "serpapi", "bing").
2. Declare `Capabilities` — what this provider supports.
3. Implement `is_available()` — cheap pre-flight check (no HTTP).
4. Implement `search()` — returns list[SearchResult].
   Must raise ProviderUnavailable on quota/auth failures.
   Must raise ProviderParseError if the response arrived but
   parsing failed entirely.

Capabilities
------------
SearchManager reads capabilities before calling a provider so it
can adapt automatically.  Example: if `supports_pagination` is False,
SearchManager won't send a page > 0 to that provider.

Adding a new provider
---------------------
Create a file in search/providers/, subclass SearchProvider,
register it in search/registry.py.  Nothing else changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from search.result import SearchResult
from network_client_project.network.middleware.base import Request


@dataclass(frozen=True)
class Capabilities:
    """
    What a provider is able to return.

    SearchManager uses these flags to adapt its behaviour automatically
    so nothing breaks when a provider can't return a particular field.
    """

    supports_pagination: bool = True   # Can fetch results beyond page 0
    supports_snippets:   bool = True   # Returns text snippets / descriptions
    supports_titles:     bool = True   # Returns page titles
    supports_rate_limit: bool = False  # Has a known rate limit / quota
    max_results_per_page: int = 10     # Maximum results the provider can return per call


class SearchProvider(ABC):
    """
    Abstract base class for all search providers.

    Subclass contract
    -----------------
    - Set `name`  (unique slug, lowercase, underscore-separated)
    - Set `capabilities`
    - Implement `is_available()`
    - Implement `search()`
    """

    # Unique lowercase slug — used in registry, config, and logging
    name: str = "base"

    # Advertised capabilities — override in subclass as a class attribute
    capabilities: Capabilities = Capabilities()

    # ── Abstract interface ────────────────────────────────────────────────────

    @abstractmethod
    def is_available(self) -> bool:
        """
        Return True when this provider can serve requests right now.

        This is a cheap, synchronous check (no HTTP).
        Examples: check that an API key is set, or that the provider
        has not been disabled via config flag.
        """

    @abstractmethod
    def search(
        self,
        request_or_query: Request | str,
        max_results: int = 10,
        page: int = 0,
    ) -> list[SearchResult]:
        """
        Execute a search and return a list of SearchResult objects.

        Parameters
        ----------
        request_or_query : Request object or raw search query string
        max_results      : Maximum number of results to return
        page             : Zero-based page index (offset = page * max_results)

        Raises
        ------
        ProviderUnavailable : quota exceeded, credentials missing, rate-limited
        ProviderParseError  : response received but parsing completely failed
        """

    # ── Helpers (concrete, not overridden normally) ───────────────────────────

    def __repr__(self) -> str:
        available = "available" if self.is_available() else "unavailable"
        return f"<{self.__class__.__name__} name={self.name!r} {available}>"
