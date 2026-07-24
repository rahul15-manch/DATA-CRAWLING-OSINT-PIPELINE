import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from search.provider_base import SearchProvider, Capabilities
from search.result import SearchResult
from search.exceptions import ProviderUnavailable
from pillar3.network.middleware.base import Request
from search.providers.directory_provider import _build_query_candidates

logger = logging.getLogger(__name__)

class RepositoryProvider(SearchProvider):
    """
    Search provider that queries repository systems (GitHub, GitLab, Bitbucket)
    to discover company/organization profiles.
    """
    name = "repository_provider"
    capabilities = Capabilities(supports_pagination=False)

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

        candidates = [query] + [candidate for candidate in _build_query_candidates(query) if candidate != query]
        for candidate in candidates[:3]:
            def _fetch_github() -> list[SearchResult]:
                try:
                    gh_url = f"https://api.github.com/search/users?q={candidate}+type:org"
                    resp = client.get(gh_url, provider="repository_provider", session_id="repository:github", timeout=10.0)
                    if resp.status_code != 200:
                        return []
                    data = json.loads(resp.text)
                    items: list[SearchResult] = []
                    for item in data.get("items", [])[:max_results]:
                        url = item.get("html_url")
                        if not url:
                            continue
                        items.append(SearchResult(
                            url=url,
                            title=f"{item.get('login')} (GitHub Org)",
                            snippet=f"GitHub Organization profile for {item.get('login')}"
                        ))
                    return items
                except Exception as e:
                    logger.warning(f"[RepositoryProvider] GitHub search failed: {e}")
                    return []

            def _fetch_gitlab() -> list[SearchResult]:
                try:
                    gl_url = f"https://gitlab.com/api/v4/groups?search={candidate}"
                    resp = client.get(gl_url, provider="repository_provider", session_id="repository:gitlab", timeout=10.0)
                    if resp.status_code != 200:
                        return []
                    groups = json.loads(resp.text)
                    items: list[SearchResult] = []
                    for g in groups[:max_results]:
                        url = g.get("web_url")
                        if not url:
                            continue
                        items.append(SearchResult(
                            url=url,
                            title=f"{g.get('name')} (GitLab Group)",
                            snippet=f"GitLab Group namespace: {g.get('description') or g.get('path')}"
                        ))
                    return items
                except Exception as e:
                    logger.warning(f"[RepositoryProvider] GitLab search failed: {e}")
                    return []

            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(_fetch_github), executor.submit(_fetch_gitlab)]
                for future in as_completed(futures):
                    for item in future.result():
                        if item.url in seen_urls:
                            continue
                        seen_urls.add(item.url)
                        results.append(item)
                    if len(results) >= max_results:
                        for pending in futures:
                            pending.cancel()
                        break

            if len(results) >= max_results:
                break

        return results[:max_results]
