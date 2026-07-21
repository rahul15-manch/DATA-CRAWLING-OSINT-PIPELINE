import logging
import threading
import atexit
from playwright.sync_api import sync_playwright, Playwright

from pillar1.browser.browser_pool import BrowserPool
from pillar1.browser.cookie_manager import CookieManager

logger = logging.getLogger("pillar1.browser")

class BrowserManager:
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self.playwright: Playwright = None
        self.pool: BrowserPool = None
        self.cookie_manager = CookieManager()
        self._initialized = False

    @classmethod
    def get_instance(cls) -> 'BrowserManager':
        """Singleton entry point with thread-safe locking."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def initialize(self):
        """Lazy initialization of Playwright and BrowserPool (thread-safe)."""
        with self._lock:
            if self._initialized:
                return
                
            logger.info("[BrowserManager] Lazy-initializing Playwright driver (sync)...")
            import asyncio
            try:
                # Set event loop to None to prevent Playwright Sync API from raising event loop conflicts
                asyncio.set_event_loop(None)
            except Exception:
                pass
            self.playwright = sync_playwright().start()
            self.pool = BrowserPool(self.playwright)
            self.pool.initialize()
            self._initialized = True
            
            # Register a cleanup hook on process exit
            atexit.register(self.shutdown)

    def get_browser(self, provider: str = None):
        """Fetches the healthiest proxy-bound BrowserInstance from the pool."""
        if not self._initialized:
            self.initialize()
        return self.pool.get_browser(provider)

    def shutdown(self):
        """Gracefully shuts down all pools and terminates Playwright session."""
        with self._lock:
            if not self._initialized:
                return
            logger.info("[BrowserManager] Shutting down BrowserManager pool...")
            if self.pool:
                self.pool.stop_all()
            if self.playwright:
                try:
                    self.playwright.stop()
                except Exception as e:
                    logger.error(f"[BrowserManager] Error stopping Playwright: {e}")
            self._initialized = False
            self.playwright = None
            self.pool = None
            
            try:
                atexit.unregister(self.shutdown)
            except Exception:
                pass

def get_browser_manager() -> BrowserManager:
    """Convenience helper to retrieve the BrowserManager singleton."""
    return BrowserManager.get_instance()
