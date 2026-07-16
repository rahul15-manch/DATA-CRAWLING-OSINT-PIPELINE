import random
import time
from bs4 import BeautifulSoup
from urllib.parse import quote_plus
from search.provider_base import SearchProvider, Capabilities
from search.result import SearchResult
from search.exceptions import ProviderUnavailable, ProviderParseError
from network_client_project.network.middleware.base import Request

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
        return True

    def search(self, request_or_query: Request | str, max_results: int = 10, page: int = 0) -> list[SearchResult]:
        if isinstance(request_or_query, Request):
            query = request_or_query.query or ""
        else:
            query = request_or_query

        if time.time() < self._cooldown_until:
            remaining = int(self._cooldown_until - time.time())
            raise ProviderUnavailable(self.name, f"Brave cooling down for {remaining}s after HTTP 429")

        url = f"https://search.brave.com/search?q={quote_plus(query)}"
        from network_client_project.network.client import get_network_client
        client = get_network_client()
        

        for attempt in range(1, 5):
            try:
                # ProxyMiddleware handles direct_first policy via provider tag
                resp = client.get(
                    url,
                    session_id=self._cookie_session_id,
                    provider="brave",
                    timeout=15.0,
                    headers={
                        "Accept-Language": "en-US,en;q=0.9",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                        "Cache-Control": "no-cache",
                    },
                )
            except Exception as e:
                raise ProviderUnavailable(self.name, str(e))

            if resp.status_code == 429:
                wait_for = self._next_backoff()
                self._cooldown_until = time.time() + wait_for
                if attempt < 4:
                    time.sleep(wait_for + random.uniform(0.5, 1.5))
                    continue
                raise ProviderUnavailable(self.name, "Brave HTTP 429 rate limit")

            if resp.status_code != 200:
                raise ProviderUnavailable(self.name, f"HTTP Error {resp.status_code}")

            soup = BeautifulSoup(resp.text, "html.parser")
            results = []
            
            # Parse Brave search results
            blocks = soup.find_all("div", class_="snippet")
            for block in blocks[:max_results]:
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
                    
                results.append(SearchResult(url=link, title=title, snippet=snippet))

            self._reset_backoff()
            return results
