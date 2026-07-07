import random
import threading
import time
import logging
from typing import List, Optional, Dict
from dataclasses import dataclass
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

@dataclass
class Proxy:
    """Represents a single Proxy and its health state."""
    raw_url: str
    success_count: int = 0
    failure_count: int = 0
    cooldown_until: float = 0.0
    
    @property
    def formatted(self) -> Dict[str, str]:
        """Returns the proxy formatted for requests/httpx dictionaries."""
        # A proper proxy string could be: http://user:pass@1.2.3.4:8080
        # If it doesn't have a scheme, default to http
        url = self.raw_url if "://" in self.raw_url else f"http://{self.raw_url}"
        return {
            "http": url,
            "https": url
        }

    @property
    def is_cooling_down(self) -> bool:
        return time.time() < self.cooldown_until

    def record_success(self):
        self.success_count += 1
        self.failure_count = 0  # Reset on success
        self.cooldown_until = 0.0

    def record_failure(self, cooldown_seconds: float = 60.0):
        self.failure_count += 1
        self.cooldown_until = time.time() + cooldown_seconds


class ProxyManager:
    """
    Manages a pool of proxies, handling rotation, health scoring, 
    and thread-safe access.
    """
    def __init__(self):
        self._proxies: List[Proxy] = []
        # Thread safety is critical when multiple crawler threads ask for proxies simultaneously
        self._lock = threading.Lock()
        # Track sticky sessions: session_id -> Proxy
        self._sticky_sessions: Dict[str, Proxy] = {}

    def load_from_list(self, proxy_list: List[str]):
        """Load proxies from a list of raw strings."""
        with self._lock:
            for p_str in proxy_list:
                self._proxies.append(Proxy(raw_url=p_str))
        logger.info(f"Loaded {len(proxy_list)} proxies into the manager.")

    def load_from_file(self, filepath: str):
        """Load proxies from a text file, one per line."""
        try:
            with open(filepath, 'r') as f:
                proxies = [line.strip() for line in f if line.strip()]
            self.load_from_list(proxies)
        except Exception as e:
            logger.error(f"Failed to load proxies from file: {e}")

    def remove_bad_proxies(self, max_failures: int = 5):
        """Permanently remove proxies that have failed too many times."""
        with self._lock:
            initial_count = len(self._proxies)
            self._proxies = [p for p in self._proxies if p.failure_count < max_failures]
            removed = initial_count - len(self._proxies)
            if removed > 0:
                logger.info(f"Removed {removed} permanently dead proxies.")
                # Also cleanup sticky sessions
                keys_to_remove = [k for k, p in self._sticky_sessions.items() if p.failure_count >= max_failures]
                for k in keys_to_remove:
                    del self._sticky_sessions[k]

    def get_proxy(self, session_id: Optional[str] = None) -> Optional[Proxy]:
        """
        Get a healthy proxy.
        If session_id is provided, implements Sticky Sessions.
        """
        self.remove_bad_proxies() # Auto-cleanup before picking
        
        with self._lock:
            if not self._proxies:
                return None

            # Sticky session logic
            if session_id:
                if session_id in self._sticky_sessions:
                    proxy = self._sticky_sessions[session_id]
                    if not proxy.is_cooling_down:
                        return proxy
                # If no sticky proxy exists, or it died, or it's cooling down, pick a new one below

            # Filter for healthy proxies
            healthy_proxies = [p for p in self._proxies if not p.is_cooling_down]
            
            if not healthy_proxies:
                logger.warning("No healthy proxies available! All are on cooldown.")
                return None

            # Random Selection (Can be upgraded to weighted rotation)
            selected = random.choice(healthy_proxies)

            # Assign to sticky session if requested
            if session_id:
                self._sticky_sessions[session_id] = selected

            return selected

    def get_stats(self) -> Dict:
        """Return analytics on the proxy pool."""
        with self._lock:
            total = len(self._proxies)
            cooling = sum(1 for p in self._proxies if p.is_cooling_down)
            return {
                "total": total,
                "healthy": total - cooling,
                "cooling_down": cooling,
            }
