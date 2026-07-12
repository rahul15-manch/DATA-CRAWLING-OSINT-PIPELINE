"""
discovery/search_backend.py
============================
COMPATIBILITY SHIM — do not add logic here.

All search functionality has been moved to the search/ package.
This file exists purely so that any code that still imports from
discovery.search_backend continues to work without modification.

The canonical imports are now:
    from search import SearchManager, SearchResult, run_search
    from search.manager import get_search_manager

DO NOT add new search logic here.
DO NOT import this module in new code.
Add new providers in search/providers/ and register in search/registry.py.
"""

# Re-export everything the old module exposed
from search.manager import (          # noqa: F401
    SearchManager,
    get_search_manager,
    run_search,
)
from search.result import SearchResult  # noqa: F401
from search.exceptions import (         # noqa: F401
    ProviderUnavailable,
    ProviderParseError,
    AllProvidersExhausted,
)
