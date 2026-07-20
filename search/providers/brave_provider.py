import random
import time
import logging
from bs4 import BeautifulSoup
from urllib.parse import quote_plus
from search.provider_base import SearchProvider, Capabilities
from search.result import SearchResult
from search.exceptions import ProviderUnavailable, ProviderParseError
from network_client_project.network.middleware.base import Request
import config

logger = logging.getLogger(__name__)

class BraveProvider(SearchProvider):
    name = "brave"
    capabilities = Capabilities(supports_pagination=True)

    def __init__(self):
        self._cookie_session_id = "brave:search"
        self._cooldown_until = 0.0
        self._backoff_index = 0

    def _next_backoff(self) -> int:
        sequence = [3, 6, 12, 24]
        step = min(self._backoff_index, len(sequence) - 1)
        self._backoff_index = min(self._backoff_index + 1, len(sequence) - 1)
        return sequence[step]

    def _reset_backoff(self) -> None:
        self._cooldown_until = 0.0
        self._backoff_index = 0

    def is_available(self) -> bool:
        return getattr(config, "ENABLE_BRAVE", True)

    def search(self, request_or_query: Request | str, max_results: int = 10, page: int = 0) -> list[SearchResult]:
        if isinstance(request_or_query, Request):
            query = request_or_query.query or ""
            page = request_or_query.meta.get("page", 0)
            max_results = request_or_query.meta.get("max_results", 10)
        else:
            query = request_or_query

        if not self.is_available():
            raise ProviderUnavailable(self.name, "ENABLE_BRAVE is False")

        if time.time() < self._cooldown_until:
            remaining = int(self._cooldown_until - time.time())
            raise ProviderUnavailable(self.name, f"Brave cooling down for {remaining}s after HTTP 429")

        api_key = getattr(config, "BRAVE_SEARCH_API_KEY", "").strip()
        
        # 1. API Mode
        if api_key:
            print(f"[BraveProvider] Using Brave Search API")
            url = f"https://api.search.brave.com/res/v1/web/search?q={quote_plus(query)}"
            if page > 0:
                url += f"&offset={page * max_results}"
            
            from network_client_project.network.client import get_network_client
            client = get_network_client()
            
            try:
                resp = client.get(
                    url,
                    session_id=self._cookie_session_id,
                    provider="brave",
                    timeout=15.0,
                    headers={
                        "Accept": "application/json",
                        "X-Subscription-Token": api_key,
                    }
                )
                if resp.status_code == 429:
                    wait_for = self._next_backoff()
                    self._cooldown_until = time.time() + wait_for
                    raise ProviderUnavailable(self.name, "Brave Search API 429 Rate Limit")
                if resp.status_code != 200:
                    raise ProviderUnavailable(self.name, f"Brave Search API HTTP Error {resp.status_code}")
                
                data = resp.json()
                results = []
                web = data.get("web", {})
                for rank, item in enumerate(web.get("results", [])[:max_results], start=1):
                    results.append(
                        SearchResult(
                            url=item.get("url"),
                            title=item.get("title"),
                            snippet=item.get("description"),
                            provider=self.name,
                            source="Brave API",
                            provider_rank=rank,
                            query=query,
                            page=page,
                            timestamp=time.time(),
                        )
                    )
                self._reset_backoff()
                return results
            except Exception as e:
                raise ProviderUnavailable(self.name, f"Brave Search API request failed: {e}")

        # 2. HTML Scraper Mode Fallback
        print(f"[BraveProvider] Falling back to Brave Search HTML Scraper")
        url = f"https://search.brave.com/search?q={quote_plus(query)}"
        if page > 0:
            url += f"&offset={page}" # Brave HTML offset
            
        from network_client_project.network.client import get_network_client
        client = get_network_client()

        for attempt in range(1, 3):
            from utils.deadline import Deadline
            if attempt > 1 and Deadline.is_exceeded():
                logger.warning("[BraveProvider] Global deadline exceeded. Aborting Brave search retries.")
                break

            try:
                if attempt == 1:
                    time.sleep(random.uniform(1.5, 3.0))
                resp = client.get(
                    url,
                    session_id=self._cookie_session_id,
                    provider="brave",
                    timeout=15.0,
                    headers={
                        "Accept-Language": "en-US,en;q=0.9",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                        "Accept-Encoding": "gzip, deflate",
                        "Cache-Control": "no-cache",
                        "Referer": "https://search.brave.com/",
                    },
                )
            except Exception as e:
                raise ProviderUnavailable(self.name, f"Failed to perform, {e}")

            if resp.status_code == 429:
                wait_for = self._next_backoff()
                self._cooldown_until = time.time() + wait_for
                if attempt < 2:
                    time.sleep(wait_for + random.uniform(0.5, 1.5))
                    continue
                raise ProviderUnavailable(self.name, "Brave Scraper HTTP 429 rate limit")

            if resp.status_code != 200:
                raise ProviderUnavailable(self.name, f"Brave Scraper HTTP Error {resp.status_code}")

            soup = BeautifulSoup(resp.text, "html.parser")
            results = []
            
            blocks = soup.find_all("div", class_="snippet")
            for rank, block in enumerate(blocks[:max_results], start=1):
                a = block.find("a")
                if not a:
                    continue
                title = a.get_text(strip=True)
                link = a.get("href")
                if not link:
                    continue
                
                snippet = ""
                desc = block.find("p", class_="description")
                if desc:
                    snippet = desc.get_text(strip=True)
                    
                results.append(
                    SearchResult(
                        url=link,
                        title=title,
                        snippet=snippet,
                        provider=self.name,
                        source="Brave HTML",
                        provider_rank=rank,
                        query=query,
                        page=page,
                        timestamp=time.time(),
                    )
                )

            self._reset_backoff()
            return results
