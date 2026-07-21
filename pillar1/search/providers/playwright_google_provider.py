import os
import sys
import time
import logging
from urllib.parse import quote_plus, urlparse
from bs4 import BeautifulSoup

# Ensure correct sys.path additions
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from search.provider_base import SearchProvider, Capabilities
from search.result import SearchResult
from search.exceptions import ProviderUnavailable, ProviderParseError
from search.google_parser_registry import GoogleParserRegistry
from search.google_response_classifier import classify_google_response
from network_client_project.network.middleware.base import Request

from pillar1.browser.browser_manager import get_browser_manager

logger = logging.getLogger("pillar1.search.playwright_google")

class PlaywrightGoogleProvider(SearchProvider):
    name = "playwright_google"
    capabilities = Capabilities(supports_pagination=True)

    def __init__(self):
        # Tracking cooldowns or circuit breaker overrides
        self._cooldown_until = 0.0

    def is_available(self) -> bool:
        return time.time() >= self._cooldown_until

    def search(
        self,
        request_or_query: Request | str,
        max_results: int = 10,
        page: int = 0,
    ) -> list[SearchResult]:
        start_time = time.time()
        if isinstance(request_or_query, Request):
            query = request_or_query.query or ""
            page = request_or_query.meta.get("page", 0)
            max_results = request_or_query.meta.get("max_results", 10)
        else:
            query = request_or_query

        if time.time() < self._cooldown_until:
            remaining = int(self._cooldown_until - time.time())
            raise ProviderUnavailable(self.name, f"Playwright Google cooling down for {remaining}s")

        from pillar1.browser.browser_breaker import BrowserCircuitBreaker
        breaker = BrowserCircuitBreaker.get_instance()
        if breaker.is_blocked(self.name):
            raise ProviderUnavailable(self.name, "Browser circuit breaker is OPEN due to consecutive blocks.")

        import asyncio
        import threading
        logger.info(f"[PlaywrightGoogleProvider] Current thread: {threading.current_thread().name}")
        try:
            loop = asyncio.get_running_loop()
            logger.info(f"[PlaywrightGoogleProvider] Running event loop detected: {loop}")
        except RuntimeError:
            logger.info("[PlaywrightGoogleProvider] No running event loop detected in this thread.")

        bm = get_browser_manager()
        try:
            # Retrieve the healthiest browser from the pool specifically for Google queries
            instance = bm.get_browser("google")
        except Exception as e:
            # Trip the circuit breaker for playwright_google and raise ProviderUnavailable
            logger.warning(f"[PlaywrightGoogleProvider] BrowserPool exhausted or unavailable: {e}. Tripping circuit breaker.")
            breaker.record_failure(self.name)
            raise ProviderUnavailable(self.name, f"Browser pool exhausted: {e}")
        
        # Adaptive limit checks
        # Recycles after 40 requests for Google searches
        if instance.requests_count >= 40:
            logger.info(f"[PlaywrightGoogleProvider] BrowserInstance #{instance.index} reached Google request limit (40). Draining.")
            import threading
            threading.Thread(target=bm.pool.recycle_instance, args=(instance,), daemon=True).start()
            try:
                # Request a fresh browser from pool
                instance = bm.get_browser("google")
            except Exception as e:
                logger.warning(f"[PlaywrightGoogleProvider] BrowserPool exhausted during recycling: {e}. Tripping circuit breaker.")
                breaker.record_failure(self.name)
                raise ProviderUnavailable(self.name, f"Browser pool exhausted during recycling: {e}")

        instance.active_pages += 1
        instance.requests_count += 1

        context = None
        page_obj = None
        
        # Check ignore cert errors from config
        ignore_certs = True
        try:
            import config
            ignore_certs = getattr(config, "PLAYWRIGHT_IGNORE_CERTIFICATE_ERRORS", True)
        except Exception:
            pass
        try:
            # 1. Create context and load non-expired cookies
            cookies = bm.cookie_manager.load_cookies("google.com")
            context = instance.browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                locale="en-US",
                timezone_id="America/New_York",
                ignore_https_errors=ignore_certs
            )
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                window.chrome = { runtime: {} };
            """)
            if cookies:
                context.add_cookies(cookies)

            page_obj = context.new_page()

            # 2. Form search URL
            params = f"q={quote_plus(query)}&num={min(max_results, 10)}&hl=en&gl=us"
            if page > 0:
                params += f"&start={page * min(max_results, 10)}"
            url = f"https://www.google.com/search?{params}"

            # 3. Load page
            logger.info(f"[PlaywrightGoogleProvider] Fetching search page: {url}")
            response = page_obj.goto(url, timeout=15000, wait_until="domcontentloaded")
            
            # Handle cookie consent walls if we get redirected or blocked
            if "consent.google.com" in page_obj.url or page_obj.locator("form[action*='consent']").count() > 0:
                logger.info("[PlaywrightGoogleProvider] Consent popup/redirect detected on search page. Handling...")
                self._handle_consent(page_obj)
                # Re-load search page after consent accepted
                response = page_obj.goto(url, timeout=15000, wait_until="domcontentloaded")

            if not response:
                instance.failure_count += 1
                instance.consecutive_failures += 1
                raise ProviderUnavailable(self.name, "No response returned from Google search page.")

            # Save updated cookies back to session store
            try:
                new_cookies = context.cookies()
                bm.cookie_manager.save_cookies("google.com", new_cookies)
            except Exception as e:
                logger.warning(f"[PlaywrightGoogleProvider] Failed to save cookies: {e}")

            html = page_obj.content()
            html_size = len(html)

            # 4. Google Response Classification
            analysis = classify_google_response(html, response.status, page_obj.url)
            classification = analysis["page_type"]

            logger.info(
                f"[PlaywrightGoogleProvider] HTML Size: {html_size:,} bytes. "
                f"Page classification: {classification}"
            )

            # Record feedback metrics on the browser instance
            if classification == "CAPTCHA_PAGE":
                instance.failure_count += 1
                instance.consecutive_failures += 1
                raise ProviderUnavailable(self.name, "CAPTCHA block page detected on Playwright session.")
            elif classification == "ENABLE_JS_PAGE":
                instance.failure_count += 1
                instance.consecutive_failures += 1
                raise ProviderUnavailable(self.name, "JavaScript redirection requested (stealth bypass failed).")
            elif classification in ("SORRY_PAGE", "GOOGLE_SORRY_PAGE"):
                instance.failure_count += 1
                instance.consecutive_failures += 1
                raise ProviderUnavailable(self.name, "Google sorry limit page hit.")
            
            # Success path
            instance.success_count += 1
            instance.consecutive_failures = 0
            breaker.record_success(self.name)

            # Feedback to ProxyManager
            if instance.proxy_url:
                try:
                    from network_client_project.network.proxy_manager import get_proxy_manager
                    pm = get_proxy_manager()
                    proxy_obj = pm.get_proxy_by_url(instance.proxy_url)
                    if proxy_obj:
                        proxy_obj.record_success(domain="google.com", latency_s=(time.time() - start_time))
                except Exception:
                    pass

            if classification == "ZERO_RESULTS_PAGE":
                return []

            # 5. Execute Parser Cascade using existing parser rules
            parsers = GoogleParserRegistry.get_parsers()
            results = []
            ts = time.time()
            rank = 0

            for parser in parsers:
                try:
                    raw_extracted = parser.parse(html, max_results, query, page)
                except Exception as parse_exc:
                    raw_extracted = []
                    logger.debug(f"[PlaywrightGoogleProvider] Parser {parser.name} threw exception: {parse_exc}")

                # Map extracted raw items to SearchResult objects with provider validation
                validated = []
                for r in raw_extracted:
                    if self._validate_and_classify_result(r) != "Rejected":
                        # Override provider metadata
                        r.provider = self.name
                        r.timestamp = ts
                        validated.append(r)

                if validated:
                    results = validated
                    break

            return results

        except Exception as e:
            instance.failure_count += 1
            instance.consecutive_failures += 1
            breaker.record_failure(self.name)
            logger.error(f"[PlaywrightGoogleProvider] Query error: {e}")

            # Feedback to ProxyManager
            if instance.proxy_url:
                try:
                    from network_client_project.network.proxy_manager import get_proxy_manager
                    pm = get_proxy_manager()
                    proxy_obj = pm.get_proxy_by_url(instance.proxy_url)
                    if proxy_obj:
                        proxy_obj.record_failure(domain="google.com", error=e, cooldown_seconds=600)
                except Exception:
                    pass

            # Generalize provider block state
            err_str = str(e).lower()
            is_block = "429" in err_str or "captcha" in err_str or "sorry" in err_str
            if is_block:
                instance.blocked_until["google"] = time.time() + 600.0

            raise

        finally:
            if page_obj:
                try:
                    page_obj.close()
                except Exception:
                    pass
            if context:
                try:
                    context.close()
                except Exception:
                    pass
            instance.active_pages = max(0, instance.active_pages - 1)

    def _handle_consent(self, page):
        """Helper to bypass cookie consent buttons."""
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
                    btn.first.click(timeout=3000)
                    page.wait_for_load_state("domcontentloaded")
                    break
        except Exception as e:
            logger.debug(f"[PlaywrightGoogleProvider] Consent handle note: {e}")

    def _validate_and_classify_result(self, result: SearchResult) -> str:
        """Heuristics to reject directory profiles and search index pages."""
        url = result.url or ""
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()

        # Reject common lead aggregate index directories
        skip_domains = {
            "clutch.co", "designrush.com", "goodfirms.co", "sortlist.com",
            "g2.com", "capterra.com", "trustpilot.com", "yelp.com",
            "crunchbase.com", "upwork.com", "fiverr.com", "freelancer.com",
            "yellowpages.com", "justdial.com", "internshala.com"
        }
        for d in skip_domains:
            if d in netloc:
                return "Rejected"
                
        return "Validated"
