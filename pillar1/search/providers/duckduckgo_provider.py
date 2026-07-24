import time
from bs4 import BeautifulSoup
from search.provider_base import SearchProvider, Capabilities
from search.result import SearchResult
from search.exceptions import ProviderUnavailable, ProviderParseError
from pillar3_network_resilience.network.middleware.base import Request

class DuckDuckGoProvider(SearchProvider):
    name = "duckduckgo"
    capabilities = Capabilities(supports_pagination=True)

    def __init__(self):
        self._cookie_session_id = "duckduckgo:search"
        self._cooldown_until = 0.0
        self._consecutive_202s = 0
        self._backoff_index = 0
        self._cooldown_sequence = [30, 60, 120, 300]

    def is_available(self) -> bool:
        return True

    def search(self, request_or_query: Request | str, max_results: int = 10, page: int = 0) -> list[SearchResult]:
        if isinstance(request_or_query, Request):
            query = request_or_query.query or ""
        else:
            query = request_or_query

        if time.time() < self._cooldown_until:
            remaining = int(self._cooldown_until - time.time())
            raise ProviderUnavailable(self.name, f"DuckDuckGo cooling down for {remaining}s after anti-bot response")

        url = "https://lite.duckduckgo.com/lite/"
        from pillar3_network_resilience.network.client import get_network_client
        client = get_network_client()
        
        for attempt in range(2):
            try:
                import random
                if attempt == 0:
                    time.sleep(random.uniform(2.0, 4.0))
                else:
                    # Rotate session and add longer delay on retry
                    self._cookie_session_id = f"duckduckgo:search:{time.time()}"
                    time.sleep(random.uniform(3.0, 6.0))
                resp = client.post(
                    url,
                    session_id=self._cookie_session_id,
                    data={"q": query},
                    provider="duckduckgo",
                    timeout=15.0,
                    headers={
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": "en-US,en;q=0.9",
                        "Accept-Encoding": "gzip, deflate",
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Origin": "https://lite.duckduckgo.com",
                        "Referer": "https://lite.duckduckgo.com/",
                    },
                )
            except Exception as e:
                raise ProviderUnavailable(self.name, str(e))

            if resp.status_code in {202, 403, 429}:
                if attempt == 0:
                    # Retry once immediately with a new session
                    self._cookie_session_id = f"duckduckgo:search:{time.time()}"
                    continue
                else:
                    step = min(self._backoff_index, len(self._cooldown_sequence) - 1)
                    self._cooldown_until = time.time() + self._cooldown_sequence[step]
                    self._backoff_index += 1
                    raise ProviderUnavailable(self.name, f"Temporary anti-bot response ({resp.status_code})")
            
            if resp.status_code != 200:
                self._backoff_index = 0
                raise ProviderUnavailable(self.name, f"HTTP Error {resp.status_code}")
            
            # Break on success
            break

        self._backoff_index = 0

        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        
        # Parse DDG Lite layout
        links = soup.find_all("a", class_="result-link")
        for link_el in links[:max_results]:
            title = link_el.get_text(strip=True)
            link = link_el.get("href")
            if not link:
                continue
                
            snippet = ""
            # Move up to row and check next row for snippet
            try:
                tr = link_el.find_parent("tr")
                if tr:
                    next_tr = tr.find_next_sibling("tr")
                    if next_tr:
                        snippet_el = next_tr.find("td", class_="result-snippet")
                        if snippet_el:
                            snippet = snippet_el.get_text(strip=True)
            except Exception:
                pass
                
            results.append(SearchResult(url=link, title=title, snippet=snippet))
            
        return results
