import asyncio
import time
import logging
from typing import Dict, Any, Optional
from tenacity import retry, stop_after_attempt, wait_random_exponential, retry_if_exception_type

from curl_cffi.requests import AsyncSession
from curl_cffi.requests.exceptions import RequestException

from .config import config
from .logger import NetworkLogger
from .exceptions import ErrorDetector, NetworkClientError
from .proxy_manager import get_proxy_manager
from .user_agents import UserAgentManager
from .headers import HeaderManager

logger = logging.getLogger(__name__)

class AsyncNetworkClient:
    """
    High-performance Asynchronous Network Client using curl_cffi.
    Designed for massive concurrency with browser fingerprinting.
    """
    def __init__(self):
        self.proxy_manager = get_proxy_manager()
        if config.PROXIES:
            self.proxy_manager.load_from_list(config.PROXIES)
            
        self.ua_manager = UserAgentManager(fallback=config.FALLBACK_USER_AGENT)
        self.header_manager = HeaderManager()
        
        # A single AsyncSession maintains its own connection pool.
        self._clients: Dict[str, AsyncSession] = {}
        self._lock = asyncio.Lock()  # Async lock for thread-safe client creation
        
        # Concurrency Limiter (Semaphore)
        # Prevents us from opening 10,000 sockets at once and crashing the OS
        self._semaphore = asyncio.Semaphore(100) 

    async def _get_or_create_client(self, session_id: Optional[str] = None) -> AsyncSession:
        timeout = max(config.CONNECT_TIMEOUT, config.READ_TIMEOUT)
        if session_id is None:
            return AsyncSession(
                impersonate="chrome124",
                timeout=timeout,
                verify=config.VERIFY_SSL
            )
            
        async with self._lock:
            if session_id not in self._clients:
                client = AsyncSession(
                    impersonate="chrome124",
                    timeout=timeout,
                    verify=config.VERIFY_SSL
                )
                self._clients[session_id] = client
                
            return self._clients[session_id]

    @retry(
        stop=stop_after_attempt(config.MAX_RETRIES),
        wait=wait_random_exponential(multiplier=1, max=10),
        retry=retry_if_exception_type((RequestException, NetworkClientError))
    )
    async def get(self, url: str, session_id: Optional[str] = None):
        """
        Executes an asynchronous GET request.
        """
        # Limit global concurrency using the semaphore
        async with self._semaphore:
            proxy = self.proxy_manager.get_proxy(session_id)
            proxy_url = proxy.formatted["http"] if proxy else None
            proxies_dict = proxy.formatted if proxy else None
            
            client = await self._get_or_create_client(session_id)
            
            # Prepare Headers
            ua = getattr(client, "_custom_ua", None)
            if not ua:
                ua = self.ua_manager.get_chrome_desktop()
                client._custom_ua = ua
            headers = self.header_manager.generate_browser_headers(url, ua)
            
            # Get attempt number for logging
            attempt = 0
            if hasattr(self.get, "retry") and hasattr(self.get.retry, "statistics"):
                attempt = getattr(self.get.retry.statistics, "get", lambda x,y: 1)("attempt_number", 1) - 1

            start_time = time.time()
            try:
                # Await the network I/O
                response = await client.get(url, headers=headers, proxies=proxies_dict)
                latency = (time.time() - start_time) * 1000
                
                # Check for WAF blocks
                waf_error = ErrorDetector.detect_waf_or_captcha(response) 
                if waf_error:
                    if proxy: 
                        proxy.record_failure(cooldown_seconds=300)
                    NetworkLogger.log_request(
                        logger, "GET", url, response.status_code, latency, proxy_url,
                        retries=attempt, user_agent=ua, proxy_failed=True, cooldown=300, proxy_rotated=(attempt > 0)
                    )
                    raise waf_error
                    
                if proxy: 
                    proxy.record_success()
                
                NetworkLogger.log_request(
                    logger, "GET", url, response.status_code, latency, proxy_url,
                    retries=attempt, user_agent=ua, proxy_rotated=(attempt > 0)
                )

                response.raise_for_status()
                return response
                
            except RequestException as e:
                latency = (time.time() - start_time) * 1000
                logger.error(f"Async Network Failure on {url}: {e}")
                if proxy: 
                    proxy.record_failure()
                NetworkLogger.log_request(
                    logger, "GET", url, 0, latency, proxy_url,
                    retries=attempt, user_agent=ua, proxy_failed=True, cooldown=60, proxy_rotated=(attempt > 0)
                )
                raise e

    async def close_all(self):
        """Must be called at shutdown to gracefully close all TCP connections."""
        for client in self._clients.values():
            await client.close()  # curl_cffi uses close()
        self._clients.clear()
