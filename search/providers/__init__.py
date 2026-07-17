"""
search/providers/__init__.py
============================
Providers sub-package.

All providers are imported and exported here so that the registry can
import from a single location.
"""

from search.providers.serpapi_provider     import SerpApiProvider
from search.providers.google_cse_provider  import GoogleCseProvider
from search.providers.bing_provider        import BingProvider
from search.providers.generic_api_provider import GenericApiProvider
from search.providers.google_html_provider import GoogleHtmlProvider
from search.providers.duckduckgo_provider import DuckDuckGoProvider
from search.providers.brave_provider import BraveProvider
from search.providers.directory_provider import DirectoryProvider
from search.providers.repository_provider import RepositoryProvider
from search.providers.brightdata_provider import BrightDataProvider

__all__ = [
    "SerpApiProvider",
    "GoogleCseProvider",
    "BingProvider",
    "GenericApiProvider",
    "GoogleHtmlProvider",
    "DuckDuckGoProvider",
    "BraveProvider",
    "DirectoryProvider",
    "RepositoryProvider",
    "BrightDataProvider",
]
