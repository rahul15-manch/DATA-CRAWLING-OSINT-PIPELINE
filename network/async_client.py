import asyncio
import time
import logging
import httpx
from typing import Dict, Any, Optional
from tenacity import retry, stop_after_attempt, wait_random_exponential, retry_if_exception_type

from .config import config
from .logger import NetworkLogger
from .exceptions import ErrorDetector, NetworkClientError
from .proxy_manager import ProxyManager
from .user_agents import UserAgentManager
from .headers import HeaderManager

logger = logging.getLogger(__name__)

class AsyncNetworkClient:
    """
    High-performance Asynchronous Network Client using httpx.
    Designed for massive concurrency.
    """
    def __init__(self):
        self.proxy_manager = ProxyManager()
        if config.PROXIES:
            self.proxy_manager.load_from_list(config.PROXIES)
            
        self.ua_manager = UserAgentManager(fallback=config.FALLBACK_USER_AGENT)
        self.header_manager = HeaderManager()
        
        # In async, we manage clients instead of requests.Session
        # A single httpx.AsyncClient maintains its own connection pool.
        self._clients: Dict[str, httpx.AsyncClient] = {}
        self._lock = asyncio.Lock()  # Async lock for thread-safe client creation
        
        # Concurrency Limiter (Semaphore)
        # Prevents us from opening 10,000 sockets at once and crashing the OS
        self._semaphore = asyncio.Semaphore(100) 

    async def _get_or_create_client(self, session_id: str, proxy_url: Optional[str]) -> httpx.AsyncClient:
        async with self._lock:
            if session_id not in self._clients:
                # Configure the AsyncClient with limits and proxy
                limits = httpx.Limits(max_keepalive_connections=50, max_connections=100)
                timeout = httpx.Timeout(config.CONNECT_TIMEOUT, read=config.READ_TIMEOUT)
                
                client = httpx.AsyncClient(
                    proxy=proxy_url,
                    limits=limits,
                    timeout=timeout,
                    verify=False # Ignore SSL errors
                )
                self._clients[session_id] = client
                
            return self._clients[session_id]

    # Note: Tenacity works perfectly with async functions out of the box!
    @retry(
        stop=stop_after_attempt(config.MAX_RETRIES),
        wait=wait_random_exponential(multiplier=1, max=10),
        retry=retry_if_exception_type((httpx.RequestError, NetworkClientError))
    )
    async def get(self, url: str, session_id: str = "global") -> httpx.Response:
        """
        Executes an asynchronous GET request.
        """
        # Limit global concurrency using the semaphore
        async with self._semaphore:
            proxy = self.proxy_manager.get_proxy(session_id)
            proxy_url = proxy.formatted["http"] if proxy else None
            
            client = await self._get_or_create_client(session_id, proxy_url)
            
            # Prepare Headers
            ua = self.ua_manager.get_chrome_desktop()
            headers = self.header_manager.generate_browser_headers(url, ua)
            
            start_time = time.time()
            try:
                # Await the network I/O
                response = await client.get(url, headers=headers)
                latency = (time.time() - start_time) * 1000
                
                NetworkLogger.log_request(logger, "GET", url, response.status_code, latency, proxy_url)
                
                # Check for WAF blocks
                waf_error = ErrorDetector.detect_waf_or_captcha(response) # Assuming we adapt it for httpx
                if waf_error:
                    if proxy: proxy.record_failure()
                    raise waf_error
                    
                if proxy: proxy.record_success()
                response.raise_for_status()
                return response
                
            except httpx.RequestError as e:
                logger.error(f"Async Network Failure on {url}: {e}")
                if proxy: proxy.record_failure()
                raise e

    async def close_all(self):
        """Must be called at shutdown to gracefully close all TCP connections."""
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()
