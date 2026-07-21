import os
import sys
import time
import logging
import psutil
from playwright.sync_api import Browser, BrowserContext, Page

logger = logging.getLogger("pillar1.browser")

class BrowserInstance:
    def __init__(self, playwright_instance, proxy_url: str, index: int, recycle_limit: int = 50):
        self.playwright = playwright_instance
        self.proxy_url = proxy_url
        self.index = index
        self.recycle_limit = recycle_limit
        
        self.browser: Browser = None
        self.requests_count = 0
        self.success_count = 0
        self.failure_count = 0
        self.active_pages = 0
        self.draining = False
        self.launched_at = 0.0
        self.blocked_until = {}
        self.consecutive_failures = 0

    def launch(self) -> bool:
        try:
            self.launched_at = time.time()
            proxy_config = None
            if self.proxy_url:
                proxy_config = {"server": self.proxy_url}
            
            # Check ignore cert errors from config
            ignore_certs = True
            try:
                import config
                ignore_certs = getattr(config, "PLAYWRIGHT_IGNORE_CERTIFICATE_ERRORS", True)
            except Exception:
                pass

            args = [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                f"--playwright-browser-id={id(self)}"
            ]
            if ignore_certs:
                args.append("--ignore-certificate-errors")

            self.browser = self.playwright.chromium.launch(
                headless=True,
                proxy=proxy_config,
                args=args
            )
            self.requests_count = 0
            self.success_count = 0
            self.failure_count = 0
            self.active_pages = 0
            self.draining = False
            logger.info(f"[BrowserInstance #{self.index}] Launched successfully (Proxy: {self.proxy_url}, IgnoreCerts: {ignore_certs})")
            return True
        except Exception as e:
            logger.error(f"[BrowserInstance #{self.index}] Launch failed: {e}")
            return False

    def warm_up(self, provider_url: str, test_query: str) -> bool:
        """
        Executes a pre-flight warm-up check.
        Loads the homepage to verify the browser itself works (Phase 1).
        Executes a search query to verify proxy status for the target provider (Phase 2).
        """
        if not self.browser:
            return False
        
        # Check ignore cert errors from config
        ignore_certs = True
        try:
            import config
            ignore_certs = getattr(config, "PLAYWRIGHT_IGNORE_CERTIFICATE_ERRORS", True)
        except Exception:
            pass

        context = None
        page = None
        try:
            context = self.browser.new_context(
                viewport={"width": 1280, "height": 800},
                ignore_https_errors=ignore_certs
            )
            page = context.new_page()
            
            # 1. Load homepage to test browser health
            logger.info(f"[BrowserInstance #{self.index}] Warm-up: Navigating to {provider_url}...")
            try:
                response = page.goto(provider_url, timeout=15000, wait_until="domcontentloaded")
            except Exception as e:
                err_str = str(e).lower()
                is_tunnel_err = any(x in err_str for x in ["net::err_tunnel_connection_failed", "net::err_connection_refused", "net::err_timed_out", "net::err_name_not_resolved", "net::err_connection_closed"])
                if is_tunnel_err:
                    logger.warning(f"[BrowserInstance #{self.index}] Warm-up: Proxy connection/tunnel failed: {e}")
                    if self.proxy_url:
                        try:
                            from network_client_project.network.proxy_manager import get_proxy_manager
                            pm = get_proxy_manager()
                            proxy_obj = pm.get_proxy_by_url(self.proxy_url)
                            if proxy_obj:
                                logger.warning(f"[BrowserInstance] Marking proxy as dead due to tunnel failure: {self.proxy_url}")
                                proxy_obj.record_failure(domain="google.com", error=e, cooldown_seconds=1800)
                        except Exception:
                            pass
                else:
                    logger.warning(f"[BrowserInstance #{self.index}] Warm-up homepage navigation error: {e}")
                return False

            if not response or response.status >= 400:
                logger.warning(f"[BrowserInstance #{self.index}] Warm-up failed to load homepage: {response.status if response else 'No Response'}")
                return False
            
            # Handle consent popups (Google cookie consent page, etc.)
            self._handle_consent(page)
            
            # At this point, the homepage successfully loaded. The browser itself is healthy!
            
            # 2. Run test search query to verify proxy reputation (Phase 2)
            search_url = f"{provider_url.rstrip('/')}/search?q={test_query}"
            logger.info(f"[BrowserInstance #{self.index}] Warm-up: Executing test search query...")
            try:
                response = page.goto(search_url, timeout=15000, wait_until="domcontentloaded")
                
                # Check for 429 rate limit
                if response and response.status == 429:
                    logger.warning(f"[BrowserInstance #{self.index}] Google warm-up search blocked with HTTP 429. Flagging proxy cooldown.")
                    self.blocked_until["google"] = time.time() + 600.0
                    if self.proxy_url:
                        try:
                            from network_client_project.network.proxy_manager import get_proxy_manager
                            pm = get_proxy_manager()
                            proxy_obj = pm.get_proxy_by_url(self.proxy_url)
                            if proxy_obj:
                                proxy_obj.record_failure(domain="google.com", error=Exception("Playwright Google 429"), cooldown_seconds=600)
                        except Exception:
                            pass
                    return True # Keep browser, it's healthy, but proxy is cooling down

                # Check for CAPTCHA page content
                content = page.content()
                if "captcha" in content.lower() or "did not match any documents" in content.lower() or "sorry/index" in page.url:
                    logger.warning(f"[BrowserInstance #{self.index}] Google warm-up search flagged or blocked by CAPTCHA.")
                    self.blocked_until["google"] = time.time() + 600.0
                    if self.proxy_url:
                        try:
                            from network_client_project.network.proxy_manager import get_proxy_manager
                            pm = get_proxy_manager()
                            proxy_obj = pm.get_proxy_by_url(self.proxy_url)
                            if proxy_obj:
                                proxy_obj.record_failure(domain="google.com", error=Exception("Playwright Google CAPTCHA"), cooldown_seconds=600)
                        except Exception:
                            pass
                    return True # Keep browser, it's healthy, but proxy is cooling down

            except Exception as e:
                logger.warning(f"[BrowserInstance #{self.index}] Exception executing test search query: {e}")
                err_str = str(e).lower()
                is_tunnel_err = any(x in err_str for x in ["net::err_tunnel_connection_failed", "net::err_connection_refused", "net::err_timed_out", "net::err_name_not_resolved", "net::err_connection_closed"])
                if is_tunnel_err:
                    logger.warning(f"[BrowserInstance #{self.index}] Tunnel failed during search warm-up.")
                    return False
                self.blocked_until["google"] = time.time() + 600.0
                return True

            logger.info(f"[BrowserInstance #{self.index}] Warm-up pre-flight complete. Browser & proxy are healthy!")
            return True
        except Exception as e:
            logger.error(f"[BrowserInstance #{self.index}] Warm-up exception: {e}")
            return False
        finally:
            if page:
                try:
                    page.close()
                except Exception:
                    pass
            if context:
                try:
                    context.close()
                except Exception:
                    pass

    def _handle_consent(self, page: Page):
        """Clicks consent/accept buttons if visible."""
        try:
            selectors = [
                "button:has-text('Accept all')",
                "button:has-text('I agree')",
                "button:has-text('Accept')",
                "input[type='submit'][value*='agree']",
                "form[action*='consent'] button"
            ]
            for sel in selectors:
                btn = page.locator(sel)
                if btn.count() > 0:
                    logger.info(f"[BrowserInstance #{self.index}] Consent popup detected, clicking accept...")
                    btn.first.click(timeout=3000)
                    page.wait_for_load_state("domcontentloaded")
                    break
        except Exception as e:
            logger.debug(f"[BrowserInstance #{self.index}] Non-critical consent check note: {e}")

    def get_memory_usage(self) -> float:
        """Returns browser process RSS memory footprint in MB for this specific instance process tree."""
        try:
            unique_flag = f"--playwright-browser-id={id(self)}"
            root_proc = None
            
            # Find the root Chromium process for this specific instance using the unique flag
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    cmd = proc.info['cmdline']
                    if cmd and any(unique_flag in arg for arg in cmd):
                        root_proc = proc
                        break
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            
            if not root_proc:
                return 0.0
            
            total_rss = root_proc.memory_info().rss
            for child in root_proc.children(recursive=True):
                try:
                    total_rss += child.memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
                    
            return total_rss / (1024 * 1024)
        except Exception as e:
            logger.debug(f"[BrowserInstance #{self.index}] Memory lookup failed: {e}")
            return 0.0

    def close(self):
        """Cleanly closes the browser instance and releases resources."""
        try:
            if self.browser and self.browser.is_connected():
                self.browser.close()
                logger.info(f"[BrowserInstance #{self.index}] Browser instance closed cleanly.")
        except Exception as e:
            logger.warning(f"[BrowserInstance #{self.index}] Error closing browser: {e}")

    def get_recycled_context_options(self) -> Dict[str, Any]:
        """Returns context options for recycling browser sessions with subtle, realistic variations."""
        import random
        viewports = [
            {"width": 1280, "height": 800},
            {"width": 1366, "height": 768},
            {"width": 1440, "height": 900},
            {"width": 1536, "height": 864},
            {"width": 1920, "height": 1080}
        ]
        color_schemes = ["light", "dark", "no-preference"]
        locales = ["en-US", "en-GB", "en-CA"]
        
        return {
            "viewport": random.choice(viewports),
            "color_scheme": random.choice(color_schemes),
            "locale": random.choice(locales),
            "timezone_id": "America/New_York",
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
