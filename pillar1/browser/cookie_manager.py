import os
import json
import time
import logging
from typing import List, Dict

logger = logging.getLogger("pillar1.browser")

class CookieManager:
    def __init__(self, base_dir: str = "cookies"):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)

    def _get_cookie_file(self, domain: str) -> str:
        """Returns target file path partitioned by domain/provider."""
        # Sanitize domain name for directory structures
        safe_domain = domain.replace("https://", "").replace("http://", "").replace("www.", "").strip("/")
        safe_domain = "".join(c for c in safe_domain if c.isalnum() or c in (".", "_", "-"))
        
        domain_dir = os.path.join(self.base_dir, safe_domain)
        os.makedirs(domain_dir, exist_ok=True)
        return os.path.join(domain_dir, "session_cookies.json")

    def load_cookies(self, domain: str) -> List[Dict]:
        """Loads and returns only non-expired cookies for the given domain."""
        cookie_file = self._get_cookie_file(domain)
        if not os.path.exists(cookie_file):
            return []

        try:
            with open(cookie_file, "r", encoding="utf-8") as f:
                cookies = json.load(f)
            
            if not isinstance(cookies, list):
                logger.warning(f"[CookieManager] Invalid cookies format in {cookie_file}. Starting fresh.")
                return []

            # Filter out expired cookies
            now = time.time()
            valid_cookies = []
            for c in cookies:
                # Playwright cookies have an 'expires' field (int or float timestamp)
                expires = c.get("expires")
                if expires is not None:
                    # In playwright, -1 or extremely high values denote session cookies that don't expire
                    if expires > 0 and expires < now:
                        logger.debug(f"[CookieManager] Discarding expired cookie: {c.get('name')} (expired at {expires})")
                        continue
                valid_cookies.append(c)
                
            return valid_cookies
        except Exception as e:
            logger.error(f"[CookieManager] Error loading cookies for {domain}: {e}")
            return []

    def save_cookies(self, domain: str, cookies: List[Dict]):
        """Saves cookies for the given domain to disk."""
        cookie_file = self._get_cookie_file(domain)
        try:
            # We want to preserve session structures cleanly
            with open(cookie_file, "w", encoding="utf-8") as f:
                json.dump(cookies, f, indent=2, ensure_ascii=False)
            logger.info(f"[CookieManager] Successfully saved {len(cookies)} cookies for {domain}")
        except Exception as e:
            logger.error(f"[CookieManager] Error saving cookies for {domain}: {e}")

    def clear_expired_cookies(self, domain: str):
        """Forces clearing and overwriting the cookies file to discard expired entries."""
        valid_cookies = self.load_cookies(domain)
        self.save_cookies(domain, valid_cookies)
