"""
search/registry.py
==================
Provider Registry — the ONLY place where provider names are mapped to classes.

Design
------
- `PROVIDER_REGISTRY` is a plain dict: name → class.
- SearchManager loops over it; no if/elif chains anywhere.
- Adding a new provider = one import + one dict entry here.
  Nothing else in the codebase needs to change.

To add a new provider
---------------------
1. Create search/providers/my_provider.py  (subclass SearchProvider)
2. Add one line here:
       from search.providers.my_provider import MyProvider
       "my_provider": MyProvider,
3. Add "my_provider" to SEARCH_PROVIDER_PRIORITY in config.py (or .env).

That's it.
"""

from search.providers.serpapi_provider    import SerpApiProvider
from search.providers.google_cse_provider import GoogleCseProvider
from search.providers.bing_provider       import BingProvider
from search.providers.generic_api_provider import GenericApiProvider
from search.providers.google_html_provider import GoogleHtmlProvider

# ── Master registry ───────────────────────────────────────────────────────────
# key   : provider slug used in config / env vars
# value : provider class (NOT an instance — SearchManager instantiates lazily)

PROVIDER_REGISTRY: dict[str, type] = {
    "google_html": GoogleHtmlProvider,   # Primary — Chrome TLS impersonation via curl_cffi
    "serpapi":     SerpApiProvider,       # Optional — requires SERPAPI_KEY
    "google_cse":  GoogleCseProvider,    # Optional — requires GOOGLE_CSE_KEY + GOOGLE_CSE_CX
    "generic_api": GenericApiProvider,   # Optional — requires ENABLE_CUSTOM_PROVIDER + CUSTOM_PROVIDER_URL
    "bing":        BingProvider,         # Final fallback — always available, no key required
}

# ── Default priority order ────────────────────────────────────────────────────
# Overridden by SEARCH_PROVIDER_PRIORITY env var or config.py.
# Google HTML is the primary provider (uses curl_cffi Chrome TLS impersonation).
# Bing is the final fallback — always available, no key required.

DEFAULT_PRIORITY: list[str] = [
    "google_html",  # Primary: Google HTML via curl_cffi Chrome impersonation
    "serpapi",      # Optional: API-based Google results (requires key)
    "google_cse",   # Optional: Google Custom Search API (requires key)
    "generic_api",  # Optional: any custom REST provider
    "bing",         # Fallback: always available
]
