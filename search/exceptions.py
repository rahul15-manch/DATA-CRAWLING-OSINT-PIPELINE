"""
search/exceptions.py
====================
All search-layer exception types.

Design
------
- ProviderUnavailable  : quota exceeded, credentials missing, rate-limited.
                         SearchManager catches this and moves to the next
                         provider in the priority list.
- ProviderParseError   : the provider responded successfully but the result
                         parser failed to extract usable data.
- AllProvidersExhausted: every provider in the priority list failed or was
                         unavailable.  Discovery receives an empty list.
"""


class SearchError(Exception):
    """Base class for all search-layer exceptions."""


class ProviderUnavailable(SearchError):
    """
    Raised by a provider when it cannot serve the request.

    Causes
    ------
    - API key missing or invalid
    - Quota / rate-limit exceeded (HTTP 429)
    - Provider disabled via config flag
    - Network-level connection failure that is permanent for this run

    SearchManager catches this and falls over to the next provider.
    """

    def __init__(self, provider_name: str, reason: str = ""):
        self.provider_name = provider_name
        self.reason = reason
        super().__init__(
            f"[{provider_name}] unavailable: {reason}" if reason
            else f"[{provider_name}] unavailable"
        )


class ProviderParseError(SearchError):
    """
    Raised when an HTTP response was received but could not be parsed.

    SearchManager logs this but does NOT treat it as a full failover trigger
    unless zero results are returned.
    """

    def __init__(self, provider_name: str, reason: str = ""):
        self.provider_name = provider_name
        self.reason = reason
        super().__init__(f"[{provider_name}] parse error: {reason}")


class AllProvidersExhausted(SearchError):
    """
    Raised by SearchManager when every provider in the priority list has
    either been marked unhealthy or raised ProviderUnavailable.
    Discovery modules receive an empty list, not an exception.
    """
