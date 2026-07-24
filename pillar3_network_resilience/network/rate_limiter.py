import time
import random
import threading
from typing import Dict
import logging

logger = logging.getLogger(__name__)

class TokenBucketRateLimiter:
    """
    A Thread-Safe Token Bucket implementation.
    Allows for steady rate limiting while permitting controlled bursts.
    """
    def __init__(self, capacity: int, refill_rate_per_sec: float):
        self.capacity = capacity
        self.tokens = float(capacity)
        self.refill_rate = refill_rate_per_sec
        self.last_refill_time = time.time()
        self._lock = threading.Lock()

    def consume(self, tokens_needed: int = 1, wait: bool = True) -> bool:
        """
        Attempts to consume a token. If wait=True, it will block until a token is available.
        """
        with self._lock:
            while True:
                now = time.time()
                # Refill tokens based on time passed
                time_passed = now - self.last_refill_time
                self.tokens = min(self.capacity, self.tokens + time_passed * self.refill_rate)
                self.last_refill_time = now

                if self.tokens >= tokens_needed:
                    self.tokens -= tokens_needed
                    return True
                
                if not wait:
                    return False
                
                # Calculate how long to wait for the next token
                deficit = tokens_needed - self.tokens
                wait_time = deficit / self.refill_rate
                
                # Release lock while sleeping to not block other threads from checking
                self._lock.release()
                time.sleep(wait_time)
                self._lock.acquire()

class HumanDelayGenerator:
    """
    Generates human-like pauses. Humans don't click pages every 1.000 seconds.
    """
    @staticmethod
    def standard_delay(min_sec: float = 1.0, max_sec: float = 3.5):
        """Standard random delay between page loads."""
        delay = random.uniform(min_sec, max_sec)
        time.sleep(delay)

    @staticmethod
    def simulate_reading(min_sec: float = 15.0, max_sec: float = 45.0):
        """Simulate a user reading an article before clicking the next link."""
        delay = random.uniform(min_sec, max_sec)
        logger.debug(f"Simulating human reading for {delay:.2f} seconds...")
        time.sleep(delay)

class DomainRateManager:
    """
    Manages rate limits on a per-domain basis to ensure we don't DDOS targets.
    """
    def __init__(self):
        self._domain_limiters: Dict[str, TokenBucketRateLimiter] = {}
        self._lock = threading.Lock()

    def set_domain_limit(self, domain: str, max_requests_per_second: float, max_burst: int = 5):
        with self._lock:
            self._domain_limiters[domain] = TokenBucketRateLimiter(
                capacity=max_burst, 
                refill_rate_per_sec=max_requests_per_second
            )

    def wait_for_domain(self, domain: str):
        """
        Blocks the current thread until it is safe to send a request to the domain.
        """
        limiter = None
        with self._lock:
            limiter = self._domain_limiters.get(domain)
            
        if limiter:
            limiter.consume(wait=True)
