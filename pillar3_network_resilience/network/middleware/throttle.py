import time
import logging
from urllib.parse import urlparse
from typing import Optional, Union, Any, Dict
from .base import BaseMiddleware, Request, Response
from ..config import config
from ..exceptions import ErrorDetector
from ..rate_limiter import HumanDelayGenerator

logger = logging.getLogger(__name__)

class ThrottleMiddleware(BaseMiddleware):
    """
    Middleware that manages per-domain rate limits and AutoThrottle adjustments.
    Strictly HTTP-level.
    """
    priority = 300
    def __init__(self):
        super().__init__()
        # Cache of current rate limits per domain to track AutoThrottle state
        self.current_rates: Dict[str, float] = {}

    def process_request(self, request: Request, client: Any) -> Optional[Union[Request, Response]]:
        domain = urlparse(request.url).netloc
        
        # Initialize domain rate limiter if not already present
        # Initialize domain rate limiter with custom limits (linkedin=1 rps, github=2 rps, others=0.5 rps)
        if domain not in client.rate_manager._domain_limiters:
            if "linkedin.com" in domain:
                initial_rate = 1.0
            elif "github.com" in domain:
                initial_rate = 2.0
            else:
                initial_rate = 0.5
            self.current_rates[domain] = initial_rate
            client.rate_manager.set_domain_limit(domain, initial_rate)

        # Enforce rate limit
        client.rate_manager.wait_for_domain(domain)

        # Apply human-like delay
        HumanDelayGenerator.standard_delay(config.MIN_DELAY, config.MAX_DELAY)
        return None

    def process_response(self, request: Request, response: Response, client: Any) -> Union[Request, Response]:
        domain = urlparse(response.url).netloc
        latency_s = response.latency_ms / 1000.0
        
        # Read the current rate
        current_rate = self.current_rates.get(domain, config.GLOBAL_RATE_LIMIT)
        new_rate = current_rate

        # AutoThrottle logic:
        # Check if response is blocked/WAF or rate-limited
        waf_error = ErrorDetector.detect_waf_or_captcha(response)
        if response.status_code == 429:
            new_rate = max(0.05, current_rate * 0.4)
            logger.warning(f"[AutoThrottle] 429 Rate Limit hit on {domain}. Reducing rate: {current_rate:.2f} rps -> {new_rate:.2f} rps.")
        elif waf_error:
            # WAF block: Throttle down severely
            new_rate = max(0.05, current_rate * 0.5)
            logger.warning(f"[AutoThrottle] Block detected on {domain}. Reducing rate: {current_rate:.2f} rps -> {new_rate:.2f} rps.")
        elif latency_s > 2.0:
            # High latency: Throttle down slightly
            new_rate = max(0.1, current_rate * 0.8)
            logger.info(f"[AutoThrottle] High latency ({latency_s:.2f}s) on {domain}. Reducing rate: {current_rate:.2f} rps -> {new_rate:.2f} rps.")
        elif latency_s < 0.8:
            # Low latency: Boost rate slightly
            new_rate = min(2.0, current_rate * 1.1)
            if new_rate != current_rate:
                logger.debug(f"[AutoThrottle] Healthy latency ({latency_s:.2f}s) on {domain}. Increasing rate: {current_rate:.2f} rps -> {new_rate:.2f} rps.")

        if new_rate != current_rate:
            self.current_rates[domain] = new_rate
            client.rate_manager.set_domain_limit(domain, new_rate)

        return response
