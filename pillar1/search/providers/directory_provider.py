import logging
import random
import time
import re
from abc import ABC, abstractmethod
from bs4 import BeautifulSoup
from urllib.parse import quote_plus, urlparse, urljoin
from concurrent.futures import ThreadPoolExecutor

from search.provider_base import SearchProvider, Capabilities
from search.result import SearchResult
from pillar3.network.middleware.base import Request

logger = logging.getLogger(__name__)


def _build_query_candidates(keyword: str) -> list[str]:
    """Return a ranked list of company-search queries from a raw keyword."""
    value = (keyword or "").strip()
    if not value:
        return []
    candidates = [value]
    return candidates


def find_profile_urls_via_engines(keyword: str, domain: str) -> list[str]:
    """
    Search Google -> DuckDuckGo -> Brave for directory profile URLs.
    Bing is only used as a final fallback if all other engines fail.
    """
    from search.manager import get_search_manager
    sm = get_search_manager()
    
    # Preference sequence: Google -> DDG -> Brave -> Bing fallback
    engines = ["google_html", "duckduckgo", "brave", "bing"]
    query = f"site:{domain} {keyword}"
    profile_urls = []
    
    for engine_name in engines:
        try:
            instance = sm._get_instance(engine_name)
            if not instance.is_available():
                continue
                
            logger.info(f"[DirectoryProvider] Querying engine '{engine_name}' for '{query}'...")
            raw_results = instance.search(query)
            if raw_results:
                for r in raw_results:
                    if r.url and domain in r.url.lower():
                        profile_urls.append(r.url)
                if profile_urls:
                    logger.info(f"[DirectoryProvider] Found {len(profile_urls)} profiles using engine '{engine_name}'.")
                    break  # Stop sequence on first engine to return hits
        except Exception as e:
            logger.warning(f"[DirectoryProvider] Search via engine '{engine_name}' failed: {e}")
            
    return list(set(profile_urls))


def resolve_redirect(client, url: str) -> str:
    if not url.startswith("http"):
        return url
    try:
        resp = client.get(url, require_proxy=False, provider="directory_provider", timeout=5.0, allow_redirects=False)
        if resp.status_code in (301, 302, 303, 307, 308):
            loc = resp.headers.get("Location")
            if loc:
                return loc
    except Exception:
        pass
    return url


def extract_real_website(client, profile_url: str) -> str:
    """Fetch profile URL and extract the actual company website."""
    try:
        resp = client.get(profile_url, require_proxy=False, provider="directory_provider", timeout=10.0)
        if resp and resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                text = a.get_text(strip=True).lower()
                
                if not href or href.startswith("#") or href.startswith("javascript:"):
                    continue
                    
                if any(sig in href for sig in ("/profile/visit", "/directory/visit", "/company/visit", "/visit-website", "/visit/")):
                    if href.startswith("/"):
                        href = urljoin(profile_url, href)
                    return resolve_redirect(client, href)
                    
                if text in {"visit website", "website", "visit site", "visit logo", "website link", "go to website"}:
                    if href.startswith("/"):
                        href = urljoin(profile_url, href)
                    return resolve_redirect(client, href)
    except Exception as e:
        logger.warning(f"Error fetching directory profile {profile_url}: {e}")
    return profile_url


class DirectoryAdapter(ABC):
    @abstractmethod
    def query(self, client, keyword: str) -> list[SearchResult]:
        pass


class ClutchAdapter(DirectoryAdapter):
    def query(self, client, keyword: str) -> list[SearchResult]:
        profiles = find_profile_urls_via_engines(keyword, "clutch.co")
        if not profiles:
            return []
            
        results = []
        with ThreadPoolExecutor(max_workers=3) as executor:
            candidate_profiles = profiles[:3]
            futures = {
                executor.submit(extract_real_website, client, p_url): p_url
                for p_url in candidate_profiles
            }
            for future in futures:
                p_url = futures[future]
                try:
                    web_url = future.result()
                    slug = p_url.rstrip("/").split("/")[-1]
                    name = slug.replace("-", " ").title()
                    results.append(SearchResult(
                        url=web_url,
                        title=name,
                        snippet=f"Clutch Profile: {p_url}",
                        provider="directory_provider",
                        source="Clutch"
                    ))
                except Exception as e:
                    logger.warning(f"Clutch parsing failed for {p_url}: {e}")
        return results


class YellowPagesAdapter(DirectoryAdapter):
    def query(self, client, keyword: str) -> list[SearchResult]:
        profiles = find_profile_urls_via_engines(keyword, "yellowpages.com")
        if not profiles:
            return []
            
        results = []
        with ThreadPoolExecutor(max_workers=3) as executor:
            candidate_profiles = profiles[:3]
            futures = {
                executor.submit(extract_real_website, client, p_url): p_url
                for p_url in candidate_profiles
            }
            for future in futures:
                p_url = futures[future]
                try:
                    web_url = future.result()
                    slug = p_url.rstrip("/").split("/")[-1]
                    name = slug.replace("-", " ").title()
                    results.append(SearchResult(
                        url=web_url,
                        title=name,
                        snippet=f"YellowPages Profile: {p_url}",
                        provider="directory_provider",
                        source="YellowPages"
                    ))
                except Exception as e:
                    logger.warning(f"YellowPages parsing failed for {p_url}: {e}")
        return results


class GoodFirmsAdapter(DirectoryAdapter):
    def query(self, client, keyword: str) -> list[SearchResult]:
        profiles = find_profile_urls_via_engines(keyword, "goodfirms.co")
        if not profiles:
            return []
            
        results = []
        with ThreadPoolExecutor(max_workers=3) as executor:
            candidate_profiles = profiles[:3]
            futures = {
                executor.submit(extract_real_website, client, p_url): p_url
                for p_url in candidate_profiles
            }
            for future in futures:
                p_url = futures[future]
                try:
                    web_url = future.result()
                    slug = p_url.rstrip("/").split("/")[-1]
                    name = slug.replace("-", " ").title()
                    results.append(SearchResult(
                        url=web_url,
                        title=name,
                        snippet=f"GoodFirms Profile: {p_url}",
                        provider="directory_provider",
                        source="GoodFirms"
                    ))
                except Exception as e:
                    logger.warning(f"GoodFirms parsing failed for {p_url}: {e}")
        return results


class IndiaMARTAdapter(DirectoryAdapter):
    def query(self, client, keyword: str) -> list[SearchResult]:
        profiles = find_profile_urls_via_engines(keyword, "indiamart.com")
        if not profiles:
            return []
            
        results = []
        with ThreadPoolExecutor(max_workers=3) as executor:
            candidate_profiles = profiles[:3]
            futures = {
                executor.submit(extract_real_website, client, p_url): p_url
                for p_url in candidate_profiles
            }
            for future in futures:
                p_url = futures[future]
                try:
                    web_url = future.result()
                    slug = p_url.rstrip("/").split("/")[-1]
                    name = slug.replace("-", " ").title()
                    results.append(SearchResult(
                        url=web_url,
                        title=name,
                        snippet=f"IndiaMART Profile: {p_url}",
                        provider="directory_provider",
                        source="IndiaMART"
                    ))
                except Exception as e:
                    logger.warning(f"IndiaMART parsing failed for {p_url}: {e}")
        return results


class JustDialAdapter(DirectoryAdapter):
    def query(self, client, keyword: str) -> list[SearchResult]:
        profiles = find_profile_urls_via_engines(keyword, "justdial.com")
        if not profiles:
            return []
            
        results = []
        with ThreadPoolExecutor(max_workers=3) as executor:
            candidate_profiles = profiles[:3]
            futures = {
                executor.submit(extract_real_website, client, p_url): p_url
                for p_url in candidate_profiles
            }
            for future in futures:
                p_url = futures[future]
                try:
                    web_url = future.result()
                    slug = p_url.rstrip("/").split("/")[-1]
                    name = slug.replace("-", " ").title()
                    results.append(SearchResult(
                        url=web_url,
                        title=name,
                        snippet=f"JustDial Profile: {p_url}",
                        provider="directory_provider",
                        source="JustDial"
                    ))
                except Exception as e:
                    logger.warning(f"JustDial parsing failed for {p_url}: {e}")
        return results


class DirectoryProvider(SearchProvider):
    """
    Search provider that queries company directories via search engines and profile parsing.
    """
    name = "directory_provider"
    capabilities = Capabilities(supports_pagination=False)

    def __init__(self):
        super().__init__()
        self.adapters = {
            "clutch": ClutchAdapter(),
            "goodfirms": GoodFirmsAdapter(),
            "yellowpages": YellowPagesAdapter(),
            "indiamart": IndiaMARTAdapter(),
            "justdial": JustDialAdapter(),
        }

    def is_available(self) -> bool:
        return True

    def search(self, request_or_query: Request | str, max_results: int = 10, page: int = 0) -> list[SearchResult]:
        if isinstance(request_or_query, Request):
            query = request_or_query.query or ""
        else:
            query = request_or_query

        from pillar3.network.client import get_network_client
        client = get_network_client()
        results = []
        seen_urls: set[str] = set()

        for candidate in _build_query_candidates(query):
            for name, adapter in self.adapters.items():
                try:
                    res = adapter.query(client, candidate)
                    for item in res:
                        if not item.url or item.url in seen_urls:
                            continue
                        seen_urls.add(item.url)
                        results.append(item)
                except Exception as e:
                    logger.error(f"[DirectoryProvider] Adapter '{name}' query failed: {e}")
                if len(results) >= max_results:
                    return results[:max_results]

        return results[:max_results]
