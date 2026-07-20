"""
search/__init__.py
==================
Public API for the search package.

Import from here:
    from search import SearchManager, SearchResult, run_search
    from search.exceptions import ProviderUnavailable
"""

from search.manager import SearchManager, get_search_manager, run_search
from search.result  import SearchResult
from search.exceptions import (
    ProviderUnavailable,
    ProviderParseError,
    AllProvidersExhausted,
)

__all__ = [
    "SearchManager",
    "SearchResult",
    "get_search_manager",
    "run_search",
    "ProviderUnavailable",
    "ProviderParseError",
    "AllProvidersExhausted",
]
