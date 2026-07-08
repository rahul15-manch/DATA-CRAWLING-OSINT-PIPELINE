import time
import logging
from typing import Optional, Dict, Any, Union
from curl_cffi import requests
from curl_cffi.requests.exceptions import RequestException

# Import our custom modules
from .config import config
from .logger import NetworkLogger
from .exceptions import ErrorDetector
from .proxy_manager import ProxyManager
from .user_agents import UserAgentManager
from .headers import HeaderManager
from .session_manager import SessionManager
from .retry import retry_with_jitter
from .rate_limiter import DomainRateManager, HumanDelayGenerator

# Ensure logging is setup
NetworkLogger.setup(log_dir=config.LOG_DIR, level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO))
logger = logging.getLogger(__name__)

class NetworkClient:
    """
    The Master Network Client.
    Wraps all infrastructure into a clean, automated API for the scraping teams.
    """
    def __init__(self):
        # Initialize Managers
        self.proxy_manager = ProxyManager()
        all_proxies = config.get_all_proxies
        if all_proxies:
            self.proxy_manager.load_from_list(all_proxies)
        elif config.PROXY_FILE:
            self.proxy_manager.load_from_file(config.PROXY_FILE)
            
        self.ua_manager = UserAgentManager(fallback=config.FALLBACK_USER_AGENT)
        self.header_manager = HeaderManager()
        self.session_manager = SessionManager()
        self.rate_manager = DomainRateManager()
        
        logger.info("NetworkClient initialized successfully.")

    def _prepare_request(
        self, 
        method: str, 
        url: str, 
        session_id: Optional[str], 
        is_xhr: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Internal method to assemble all the camouflage before sending.
        """
        # 1. Get Session
        session = self.session_manager.get_or_create_session(session_id)
        
        # 2. Assign Proxy (Sticky if session_id is provided)
        proxy = self.proxy_manager.get_proxy(session_id)
        proxy_dict = proxy.formatted if proxy else None

        # 3. Generate User-Agent and Headers
        # Persist UA in sticky sessions to prevent rotation mid-session
        ua = getattr(session, "_custom_ua", None)
        if not ua:
            ua = self.ua_manager.get_chrome_desktop()
            session._custom_ua = ua
            
        headers = self.header_manager.generate_browser_headers(
            target_url=url, 
            user_agent=ua, 
            is_xhr=is_xhr
        )

        # Merge user-provided kwargs headers without overwriting our critical ones
        if 'headers' in kwargs:
            headers.update(kwargs.pop('headers'))

        # Pop Accept-Encoding to let requests handle decompression automatically
        headers.pop("Accept-Encoding", None)

        return {
            "session": session,
            "proxies": proxy_dict,
            "headers": headers,
            "timeout": max(config.CONNECT_TIMEOUT, config.READ_TIMEOUT), # curl_cffi timeout format
            "verify": config.VERIFY_SSL,
            "_proxy_obj": proxy,
            **kwargs
        }

    @retry_with_jitter(max_attempts=config.MAX_RETRIES)
    def _execute(
        self, 
        method: str, 
        url: str, 
        session_id: Optional[str], 
        is_xhr: bool = False,
        **kwargs
    ) -> requests.Response:
        """
        The core execution engine wrapped in our tenacity Retry Engine.
        """
        from urllib.parse import urlparse
        domain = urlparse(url).netloc
        
        # 1. Rate Limiting Check
        if domain not in self.rate_manager._domain_limiters:
            self.rate_manager.set_domain_limit(domain, config.GLOBAL_RATE_LIMIT)
        self.rate_manager.wait_for_domain(domain)

        # 2. Human Delay (Entropy)
        HumanDelayGenerator.standard_delay(config.MIN_DELAY, config.MAX_DELAY)

        # 3. Prepare Camouflage
        req_params = self._prepare_request(method, url, session_id, is_xhr, **kwargs)
        session: requests.Session = req_params.pop("session")
        current_proxy = req_params.pop("_proxy_obj", None)
        
        proxies_dict = req_params.get("proxies")
        proxy_url = proxies_dict.get("http") if proxies_dict else None
        

        start_time = time.time()
        
        try:
            # 4. SEND THE REQUEST OVER THE WIRE
            response = session.request(method, url, **req_params)
            latency = (time.time() - start_time) * 1000
            
            attempt = 0
            if hasattr(self._execute, "retry") and hasattr(self._execute.retry, "statistics"):
                attempt = getattr(self._execute.retry.statistics, "get", lambda x,y: 1)("attempt_number", 1) - 1
            
            # 5. WAF / Error Detection
            waf_error = ErrorDetector.detect_waf_or_captcha(response)
            if waf_error:
                logger.warning(f"WAF Intercept on {domain}: {type(waf_error).__name__}")
                if current_proxy:
                    current_proxy.record_failure(cooldown_seconds=300)
                NetworkLogger.log_request(
                    logger, method, url, response.status_code, latency, proxy_url,
                    retries=attempt, user_agent=req_params["headers"].get("User-Agent"),
                    proxy_failed=True, cooldown=300, proxy_rotated=(attempt > 0)
                )
                raise waf_error
                
            if current_proxy:
                current_proxy.record_success()
                
            # Log success
            NetworkLogger.log_request(
                logger, method, url, response.status_code, latency, proxy_url,
                retries=attempt, user_agent=req_params["headers"].get("User-Agent"), proxy_rotated=(attempt > 0)
            )
            
            response.raise_for_status() 
            return response
            
        except RequestException as e:
            latency = (time.time() - start_time) * 1000
            logger.error(f"Network Failure on {url}: {e}")
            attempt = 0
            if hasattr(self._execute, "retry") and hasattr(self._execute.retry, "statistics"):
                attempt = getattr(self._execute.retry.statistics, "get", lambda x,y: 1)("attempt_number", 1) - 1
                
            if current_proxy:
                current_proxy.record_failure()
                NetworkLogger.log_request(
                    logger, method, url, 0, latency, proxy_url,
                    retries=attempt, user_agent=req_params["headers"].get("User-Agent"),
                    proxy_failed=True, cooldown=60, proxy_rotated=(attempt > 0)
                )
            raise e

    # --- PUBLIC API FOR CRAWLER TEAMS ---

    def get(self, url: str, session_id: Optional[str] = None, **kwargs) -> requests.Response:
        return self._execute("GET", url, session_id, **kwargs)

    def post(self, url: str, session_id: Optional[str] = None, **kwargs) -> requests.Response:
        return self._execute("POST", url, session_id, **kwargs)
        
    def download(self, url: str, filepath: str, session_id: Optional[str] = None):
        """Downloads a large file using streaming."""
        response = self._execute("GET", url, session_id, stream=True)
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        logger.info(f"Downloaded {url} to {filepath}")
