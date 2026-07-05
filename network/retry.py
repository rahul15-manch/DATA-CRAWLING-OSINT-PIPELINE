import logging
import requests
from requests.exceptions import RequestException, Timeout, ConnectionError
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    wait_random_exponential,
    retry_if_exception_type,
    retry_if_result,
    before_sleep_log
)

logger = logging.getLogger(__name__)

# --- RETRY CONDITIONS ---

def is_retryable_exception(exception: BaseException) -> bool:
    """Determine if a network exception should trigger a retry."""
    # We retry on timeouts, connection drops, and general network failures.
    return isinstance(exception, (Timeout, ConnectionError, RequestException))

def is_retryable_status_code(response: requests.Response) -> bool:
    """Determine if an HTTP status code should trigger a retry."""
    # We retry on Rate Limits (429) and Server Errors (500, 502, 503, 504).
    # We DO NOT retry on 404 (Not Found) or 403 (Forbidden/Banned), as these usually require a new proxy,
    # not just a simple time delay.
    return response.status_code in {429, 500, 502, 503, 504}

# --- DECORATORS FOR DIFFERENT BACKOFF STRATEGIES ---

# Strategy 1: Exponential Backoff with Jitter
# Wait 2^x * multiplier + random jitter. 
# Example waits: ~2s, ~4s, ~8s, ~16s
def retry_with_jitter(max_attempts: int = 5):
    """
    The gold standard for distributed systems and crawling.
    Jitter prevents the 'Thundering Herd' problem.
    """
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_random_exponential(multiplier=1, max=60),
        retry=(retry_if_exception_type(RequestException) | retry_if_result(is_retryable_status_code)),
        before_sleep=before_sleep_log(logger, logging.WARNING)
    )

# Strategy 2: Linear Backoff (using wait_fixed for simplicity in tenacity)
# In standard tenacity, you can combine wait_fixed. Let's just use a fixed wait for demonstration.
def retry_fixed(max_attempts: int = 3, wait_seconds: int = 5):
    """
    Wait exactly 'wait_seconds' between each attempt.
    Useful for predictable, low-traffic APIs, but bad for highly rate-limited targets.
    """
    from tenacity import wait_fixed
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_fixed(wait_seconds),
        retry=(retry_if_exception_type(RequestException) | retry_if_result(is_retryable_status_code)),
        before_sleep=before_sleep_log(logger, logging.WARNING)
    )

# --- CIRCUIT BREAKER PATTERN ---
class CircuitBreaker:
    """
    A simple state machine. If we fail X times consecutively across the whole system,
    we 'open' the circuit and stop sending requests entirely to give the target (or our proxy pool) time to recover.
    """
    def __init__(self, failure_threshold: int = 20, recovery_timeout: int = 300):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.consecutive_failures = 0
        self.circuit_open_until = 0.0

    def record_success(self):
        self.consecutive_failures = 0

    def record_failure(self):
        import time
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.failure_threshold:
            logger.critical("CIRCUIT BREAKER OPEN! System-wide failure detected.")
            self.circuit_open_until = time.time() + self.recovery_timeout

    def is_open(self) -> bool:
        import time
        if time.time() < self.circuit_open_until:
            return True
        # If timeout expired, enter 'half-open' state (letting requests through to test)
        return False
