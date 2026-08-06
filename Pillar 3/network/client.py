import time
import logging
import atexit
import threading
from typing import Optional, Dict, Any, Union
from curl_cffi import requests
from curl_cffi.requests.exceptions import RequestException

# Import our custom modules
from .config import config
from .logger import NetworkLogger
from .proxy_manager import get_proxy_manager
from .user_agents import UserAgentManager
from .headers import HeaderManager
from .session_manager import SessionManager
from .rate_limiter import DomainRateManager

# Import Middleware infrastructure
from .middleware import Request, Response, MiddlewareManager
from .middleware.registry import MiddlewareRegistry
from . import signals

# Ensure logging is setup
NetworkLogger.setup(log_dir=config.LOG_DIR, level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO))
logger = logging.getLogger(__name__)

class NetworkClient:
    """
    Synchronous Network Client that processes requests via a decoupled,
    dynamically discovered middleware pipeline.
    """
    _proxy_state_loaded = False

    def __init__(self):
        # Initialize Managers
        self.proxy_manager = get_proxy_manager()
        if not type(self)._proxy_state_loaded:
            all_proxies = config.get_all_proxies
            if all_proxies:
                self.proxy_manager.load_from_list(all_proxies)
            elif config.PROXY_FILE:
                self.proxy_manager.load_from_file(config.PROXY_FILE)
            type(self)._proxy_state_loaded = True
            
        self.ua_manager = UserAgentManager(fallback=config.FALLBACK_USER_AGENT)
        self.header_manager = HeaderManager()
        self.session_manager = SessionManager()
        self.rate_manager = DomainRateManager()
        
        # Dynamically discover and instantiate ordered Downloader Middleware chain
        self.middleware_manager = MiddlewareManager(
            MiddlewareRegistry.get_ordered_middlewares()
        )
        
        # Register state saving on exit
        if not hasattr(self.proxy_manager, '_atexit_registered'):
            atexit.register(self.proxy_manager.save_state, "proxy_state.json", is_atexit=True)
            self.proxy_manager._atexit_registered = True
        
        logger.info("NetworkClient initialized with decoupled Downloader Middleware stack.")

    def send_request(self, request: Request) -> Response:
        """
        Executes a Request by routing it through the Downloader Middleware chain and HTTP client.
        Supports middleware-initiated retries transparently.
        """
        while True:
            # 1. Run process_request hooks (first to last)
            res = self.middleware_manager.process_request(request, self)
            if isinstance(res, Response):
                # Intercepted and mock response returned
                return res
            elif isinstance(res, Request):
                # Middleware requested redirect / change: restart cycle with new request
                request = res
                continue

            from urllib.parse import urlparse
            domain = urlparse(request.url).netloc
            session_id = request.meta.get("session_id")
            provider = request.meta.get("provider")
            if provider and not request.timeout:
                try:
                    from search.manager import get_search_manager
                    sm = get_search_manager()
                    request.timeout = sm.get_adaptive_timeout(provider)
                except Exception:
                    pass
            domain = request.meta.get("domain") or urlparse(request.url).netloc
            proxies_dict = request.meta.get("proxies")
            proxy_url = proxies_dict.get("http") if proxies_dict else "direct"
            
            # Domain + Proxy + Session isolated session key
            session_key = f"{session_id or 'default'}_{provider or 'default'}_{domain}_{proxy_url}"
            session = self.session_manager.get_or_create_session(
                session_key,
                provider=provider,
                domain=domain,
            )
            
            # Emit request started signal
            signals.send(signals.REQUEST_RECEIVED, request=request)
            
            start_time = time.time()
            try:
                # 2. HTTP EXECUTION OVER THE WIRE
                curl_response = session.request(
                    method=request.method,
                    url=request.url,
                    headers=request.headers,
                    proxies=proxies_dict,
                    params=request.params,
                    data=request.data,
                    json=request.json,
                    timeout=request.timeout or max(config.CONNECT_TIMEOUT, config.READ_TIMEOUT),
                    verify=request.verify if request.verify is not None else config.VERIFY_SSL
                )
                latency = (time.time() - start_time) * 1000
                
                # Wrap in custom Response
                response = Response(
                    request=request,
                    status_code=curl_response.status_code,
                    html=curl_response.text,
                    latency_ms=latency,
                    headers=dict(curl_response.headers),
                    proxy=request.proxy,
                    content=curl_response.content
                )
                
                # Inject a standard raise_for_status helper to match curl_cffi responses
                def raise_for_status():
                    if response.status_code >= 400:
                        from curl_cffi.requests.exceptions import HTTPError
                        raise HTTPError(f"HTTP Error {response.status_code} for url {response.url}", response=curl_response)
                response.raise_for_status = raise_for_status
                
                # 3. Run process_response hooks (last to first)
                res = self.middleware_manager.process_response(request, response, self)
                if isinstance(res, Request):
                    # Middleware requested retry
                    request = res
                    continue
                
                # Emit request completed signal
                signals.send(signals.REQUEST_COMPLETED, request=request, response=res)
                return res

            except Exception as e:
                # 4. Run process_exception hooks (last to first)
                res = self.middleware_manager.process_exception(request, e, self)
                if isinstance(res, Request):
                    # Middleware requested retry on exception
                    request = res
                    continue
                elif isinstance(res, Response):
                    # Exception handled and response returned
                    return res
                
                # Emit request failed signal
                signals.send(signals.REQUEST_FAILED, request=request, exception=e)
                raise e

    # --- PUBLIC API COMPATIBILITY LAYER ---

    def get(self, url: str, session_id: Optional[str] = None, require_proxy: bool = False, **kwargs) -> Response:
        """Compatibility wrapper for HTTP GET requests."""
        # Split meta keys from regular curl_cffi kwargs
        meta = {
            "session_id": session_id,
            "require_proxy": require_proxy,
            "bypass_proxy": kwargs.pop("bypass_proxy", False),
            "is_xhr": kwargs.pop("is_xhr", False),
            "auto_score": kwargs.pop("auto_score", True),
            **kwargs
        }
        
        # Build Request object
        headers = meta.pop("headers", None)
        cookies = meta.pop("cookies", None)
        params = meta.pop("params", None)
        timeout = meta.pop("timeout", None)
        verify = meta.pop("verify", None)
        
        req = Request(
            url=url,
            method="GET",
            headers=headers,
            cookies=cookies,
            params=params,
            timeout=timeout,
            verify=verify,
            meta=meta
        )
        return self.send_request(req)

    def post(self, url: str, session_id: Optional[str] = None, require_proxy: bool = False, **kwargs) -> Response:
        """Compatibility wrapper for HTTP POST requests."""
        meta = {
            "session_id": session_id,
            "require_proxy": require_proxy,
            "bypass_proxy": kwargs.pop("bypass_proxy", False),
            "is_xhr": kwargs.pop("is_xhr", False),
            "auto_score": kwargs.pop("auto_score", True),
            **kwargs
        }
        
        headers = meta.pop("headers", None)
        cookies = meta.pop("cookies", None)
        params = meta.pop("params", None)
        data = meta.pop("data", None)
        json = meta.pop("json", None)
        timeout = meta.pop("timeout", None)
        verify = meta.pop("verify", None)
        
        req = Request(
            url=url,
            method="POST",
            headers=headers,
            cookies=cookies,
            params=params,
            data=data,
            json=json,
            timeout=timeout,
            verify=verify,
            meta=meta
        )
        return self.send_request(req)
        
    def download(self, url: str, filepath: str, session_id: Optional[str] = None):
        """Downloads a file."""
        response = self.get(url, session_id=session_id)
        with open(filepath, 'wb') as f:
            f.write(response.content)
        logger.info(f"Downloaded {url} to {filepath}")


_NETWORK_CLIENT_SINGLETON: NetworkClient | None = None
_NETWORK_CLIENT_LOCK = threading.Lock()


def get_network_client() -> NetworkClient:
    """Return a shared NetworkClient so sessions and cookies persist."""

    global _NETWORK_CLIENT_SINGLETON
    if _NETWORK_CLIENT_SINGLETON is None:
        with _NETWORK_CLIENT_LOCK:
            if _NETWORK_CLIENT_SINGLETON is None:
                _NETWORK_CLIENT_SINGLETON = NetworkClient()
    return _NETWORK_CLIENT_SINGLETON
