import random
import logging
from typing import Optional
from fake_useragent import UserAgent

logger = logging.getLogger(__name__)

class UserAgentManager:
    """
    Manages generation and intelligent rotation of User-Agents.
    """
    def __init__(self, fallback: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"):
        self.fallback = fallback
        try:
            # os="windows", "mac", "linux"
            # browsers="chrome", "edge", "firefox", "safari"
            self.ua_generator = UserAgent(platforms=['pc', 'mobile'], min_percentage=1.3)
        except Exception as e:
            logger.warning(f"Failed to initialize fake_useragent, using fallback. Error: {e}")
            self.ua_generator = None

        # Hardcoded realistic fallbacks in case fake_useragent fails
        self._fallback_desktop = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0"
        ]
        
        self._fallback_mobile = [
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
            "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36"
        ]

    def get_random(self) -> str:
        """Get a completely random User-Agent."""
        if self.ua_generator:
            return self.ua_generator.random
        return random.choice(self._fallback_desktop + self._fallback_mobile)

    def get_desktop(self) -> str:
        """Get a realistic Desktop User-Agent (Windows/Mac)."""
        if self.ua_generator:
            # Filter for PC platforms to avoid returning mobile UAs when desktop is needed
            return self.ua_generator.pc
        return random.choice(self._fallback_desktop)

    def get_mobile(self) -> str:
        """Get a realistic Mobile User-Agent (iOS/Android)."""
        if self.ua_generator:
            return self.ua_generator.mobile
        return random.choice(self._fallback_mobile)

    def get_chrome_desktop(self) -> str:
        """
        Highly specific UA. 
        Critical for consistency when generating sec-ch-ua headers later.
        """
        # Hardcoding specific modern Chrome versions is often safer than pure random
        # because we need to precisely match the SEC-CH-UA headers later.
        versions = ["120.0.0.0", "121.0.0.0", "122.0.0.0"]
        v = random.choice(versions)
        return f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{v} Safari/537.36"
