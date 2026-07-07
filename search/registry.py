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
    "serpapi":     SerpApiProvider,
    "google_cse":  GoogleCseProvider,
    "bing":        BingProvider,
    "generic_api": GenericApiProvider,   # formerly "custom"
    "google_html": GoogleHtmlProvider,   # experimental — disabled by default
}

# ── Default priority order ────────────────────────────────────────────────────
# Overridden by SEARCH_PROVIDER_PRIORITY env var.
# google_html deliberately excluded from defaults (experimental).

DEFAULT_PRIORITY: list[str] = [
    "serpapi",
    "google_cse",
    "generic_api",
    "bing",
]
