import time
import logging

logger = logging.getLogger("pillar1.browser")

class BrowserCircuitBreaker:
    _instance = None
    _lock_obj = None

    def __init__(self, failure_threshold: int = 3, cooldown_duration: float = 600.0):
        self.failure_threshold = failure_threshold
        self.cooldown_duration = cooldown_duration
        self._consecutive_failures = {}
        self._cooldown_until = {}

    @classmethod
    def get_instance(cls) -> 'BrowserCircuitBreaker':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def record_failure(self, provider: str):
        """Increments block counter and trips breaker if threshold is exceeded."""
        self._consecutive_failures[provider] = self._consecutive_failures.get(provider, 0) + 1
        if self._consecutive_failures[provider] >= self.failure_threshold:
            self._cooldown_until[provider] = time.time() + self.cooldown_duration
            logger.warning(
                f"[BrowserCircuitBreaker] CAPTCHA threshold reached for '{provider}'. "
                f"Tripping circuit breaker. Cooldown active for {self.cooldown_duration}s."
            )

    def record_success(self, provider: str):
        """Resets block counters on a successful query."""
        self._consecutive_failures[provider] = 0
        if provider in self._cooldown_until:
            del self._cooldown_until[provider]

    def is_blocked(self, provider: str) -> bool:
        """Returns True if the circuit breaker is currently open (in cooldown)."""
        cooldown = self._cooldown_until.get(provider, 0.0)
        if time.time() < cooldown:
            return True
            
        # Reset cooldown once it expires
        if provider in self._cooldown_until:
            logger.info(f"[BrowserCircuitBreaker] Cooldown expired for '{provider}'. Re-entering HALF_OPEN state.")
            del self._cooldown_until[provider]
            self._consecutive_failures[provider] = 0
        return False
