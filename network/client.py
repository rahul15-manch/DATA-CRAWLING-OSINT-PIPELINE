import time
import logging
from typing import Optional, Dict, Any, Union
import requests
from requests.exceptions import RequestException

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
        if config.PROXIES:
            self.proxy_manager.load_from_list(config.PROXIES)
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
        session_id: str, 
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
        # If we have an existing UA for this session in the headers, keep it!
        # Otherwise, generate a new one. (We want to stick to Chrome for modern WAFs)
        ua = session.headers.get("User-Agent")
        if not ua:
            ua = self.ua_manager.get_chrome_desktop()
            
        headers = self.header_manager.generate_browser_headers(
            target_url=url, 
            user_agent=ua, 
            is_xhr=is_xhr
        )

        # Merge user-provided kwargs headers without overwriting our critical ones
        if 'headers' in kwargs:
            headers.update(kwargs.pop('headers'))

        return {
            "session": session,
            "proxies": proxy_dict,
            "headers": headers,
            "timeout": config.timeout_tuple,
            "verify": False,  # Disable SSL verification for shady targets by default
            **kwargs
        }

    @retry_with_jitter(max_attempts=config.MAX_RETRIES)
    def _execute(
        self, 
        method: str, 
        url: str, 
        session_id: str, 
        is_xhr: bool = False,
        **kwargs
    ) -> requests.Response:
        """
        The core execution engine wrapped in our tenacity Retry Engine.
        """
        from urllib.parse import urlparse
        domain = urlparse(url).netloc
        
        # 1. Rate Limiting Check
        # (Assuming we set a default limit for all domains if not specified)
        if domain not in self.rate_manager._domain_limiters:
            self.rate_manager.set_domain_limit(domain, config.GLOBAL_RATE_LIMIT)
        self.rate_manager.wait_for_domain(domain)

        # 2. Human Delay (Entropy)
        HumanDelayGenerator.standard_delay(config.MIN_DELAY, config.MAX_DELAY)

        # 3. Prepare Camouflage
        req_params = self._prepare_request(method, url, session_id, is_xhr, **kwargs)
        session: requests.Session = req_params.pop("session")
        
        proxy_url = req_params.get("proxies", {}).get("http")
        start_time = time.time()
        
        try:
            # 4. SEND THE REQUEST OVER THE WIRE
            response = session.request(method, url, **req_params)
            latency = (time.time() - start_time) * 1000
            
            # 5. Log the result
            NetworkLogger.log_request(logger, method, url, response.status_code, latency, proxy_url)
            
            # 6. WAF / Error Detection
            waf_error = ErrorDetector.detect_waf_or_captcha(response)
            if waf_error:
                # If we hit a WAF, log it, fail the proxy, and raise the error so Retry Engine kicks in
                logger.warning(f"WAF Intercept on {domain}: {type(waf_error).__name__}")
                # We need to tell the ProxyManager this proxy got blocked
                current_proxy = self.proxy_manager.get_proxy(session_id)
                if current_proxy:
                    current_proxy.record_failure(cooldown_seconds=300) # 5 min cooldown for WAF block
                raise waf_error
                
            # If we get here, it's a true success!
            current_proxy = self.proxy_manager.get_proxy(session_id)
            if current_proxy:
                current_proxy.record_success()
                
            # Will automatically trigger retry if status code is 500, 502, etc. (handled by tenacity config)
            response.raise_for_status() 
            return response
            
        except RequestException as e:
            latency = (time.time() - start_time) * 1000
            logger.error(f"Network Failure on {url}: {e}")
            current_proxy = self.proxy_manager.get_proxy(session_id)
            if current_proxy:
                current_proxy.record_failure()
            raise e

    # --- PUBLIC API FOR CRAWLER TEAMS ---

    def get(self, url: str, session_id: str = "global", **kwargs) -> requests.Response:
        return self._execute("GET", url, session_id, **kwargs)

    def post(self, url: str, session_id: str = "global", **kwargs) -> requests.Response:
        return self._execute("POST", url, session_id, **kwargs)
        
    def download(self, url: str, filepath: str, session_id: str = "global"):
        """Downloads a large file using streaming."""
        response = self._execute("GET", url, session_id, stream=True)
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        logger.info(f"Downloaded {url} to {filepath}")
