import random
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class UserAgentManager:
    """
    Manages generation and intelligent rotation of User-Agents.
    """
    def __init__(self, fallback: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"):
        self.fallback = fallback
        self.last_ua: Optional[str] = None
        
        try:
            from fake_useragent import UserAgent
            # os="windows", "mac", "linux"
            # browsers="chrome", "edge", "firefox", "safari"
            self.ua_generator = UserAgent(platforms=['pc', 'mobile'], min_percentage=1.3)
        except Exception as e:
            logger.warning(f"Failed to initialize fake_useragent, using fallback. Error: {e}")
            self.ua_generator = None

        # Hardcoded realistic fallbacks in case fake_useragent fails
        self._fallback_desktop = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.4; rv:124.0) Gecko/20100101 Firefox/124.0",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ]
        
        self._fallback_mobile = [
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
            "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
            "Mozilla/5.0 (iPad; CPU OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"
        ]

    def _rotate_ua(self, get_ua_func) -> str:
        """Helper to rotate UA and prevent consecutive repeats."""
        ua = get_ua_func()
        # Try a few times to get a different one
        for _ in range(5):
            if ua != self.last_ua:
                break
            ua = get_ua_func()
        self.last_ua = ua
        return ua

    def get_random(self) -> str:
        """Get a completely random User-Agent."""
        def _get():
            if self.ua_generator:
                return self.ua_generator.random
            return random.choice(self._fallback_desktop + self._fallback_mobile)
        return self._rotate_ua(_get)

    def get_desktop(self) -> str:
        """Get a realistic Desktop User-Agent (Windows/Mac/Linux)."""
        def _get():
            if self.ua_generator:
                return self.ua_generator.pc
            return random.choice(self._fallback_desktop)
        return self._rotate_ua(_get)

    def get_mobile(self) -> str:
        """Get a realistic Mobile User-Agent (iOS/Android)."""
        def _get():
            if self.ua_generator:
                return self.ua_generator.mobile
            return random.choice(self._fallback_mobile)
        return self._rotate_ua(_get)

    def get_chrome_desktop(self) -> str:
        """
        Highly specific UA. 
        Critical for consistency when generating sec-ch-ua headers later.
        """
        def _get():
            versions = ["122.0.0.0", "123.0.0.0", "124.0.0.0"]
            v = random.choice(versions)
            return f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{v} Safari/537.36"
        return self._rotate_ua(_get)
