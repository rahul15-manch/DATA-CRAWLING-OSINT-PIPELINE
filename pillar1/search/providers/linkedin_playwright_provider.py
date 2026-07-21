import os
import sys
import time
import logging
import re
from urllib.parse import urlparse
from bs4 import BeautifulSoup

# Ensure correct sys.path additions
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from search.provider_base import SearchProvider, Capabilities
from search.result import SearchResult
from search.exceptions import ProviderUnavailable
from network_client_project.network.middleware.base import Request

from pillar1.browser.browser_manager import get_browser_manager

logger = logging.getLogger("pillar1.search.linkedin_playwright")

class LinkedinPlaywrightProvider(SearchProvider):
    name = "linkedin_playwright"
    capabilities = Capabilities(supports_pagination=False)

    def __init__(self):
        self._cooldown_until = 0.0

    def is_available(self) -> bool:
        return time.time() >= self._cooldown_until

    def search(
        self,
        request_or_query: Request | str,
        max_results: int = 1,
        page: int = 0,
    ) -> list[SearchResult]:
        if isinstance(request_or_query, Request):
            query = request_or_query.query or ""
        else:
            query = request_or_query

        if time.time() < self._cooldown_until:
            remaining = int(self._cooldown_until - time.time())
            raise ProviderUnavailable(self.name, f"LinkedIn Playwright cooling down for {remaining}s")

        # 1. Resolve target LinkedIn URL
        target_url = None
        if "linkedin.com/company/" in query:
            # Ex: "https://www.linkedin.com/company/orange-mantra" or similar in query
            match = re.search(r"https?://[a-zA-Z0-9.-]*linkedin\.com/company/[a-zA-Z0-9_-]+", query)
            if match:
                target_url = match.group(0)
        else:
            # Try to parse company handle from dork formats
            # e.g., 'site:linkedin.com/company "orange mantra"' -> orange-mantra
            clean_q = query.replace("site:linkedin.com/company", "").replace('"', '').strip()
            handle = clean_q.lower().replace(" ", "-").replace("_", "-")
            handle = re.sub(r"[^a-z0-9-]", "", handle)
            if handle:
                target_url = f"https://www.linkedin.com/company/{handle}"

        if not target_url:
            logger.warning(f"[LinkedinPlaywrightProvider] Could not resolve company URL from query: {query}")
            return []

        bm = get_browser_manager()
        instance = bm.get_browser()
        
        # Adaptive recycle limit of 20 requests for LinkedIn
        if instance.requests_count >= 20:
            logger.info(f"[LinkedinPlaywrightProvider] BrowserInstance #{instance.index} reached LinkedIn request limit (20). Draining.")
            import threading
            threading.Thread(target=bm.pool.recycle_instance, args=(instance,), daemon=True).start()
            instance = bm.get_browser()

        instance.active_pages += 1
        instance.requests_count += 1

        context = None
        page = None
        try:
            # Load partition-isolated LinkedIn cookies
            cookies = bm.cookie_manager.load_cookies("linkedin.com")
            context = instance.browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                locale="en-US",
                timezone_id="America/New_York"
            )
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                window.chrome = { runtime: {} };
            """)
            if cookies:
                context.add_cookies(cookies)

            page = context.new_page()

            logger.info(f"[LinkedinPlaywrightProvider] Navigating to LinkedIn company profile: {target_url}")
            response = page.goto(target_url, timeout=15000, wait_until="domcontentloaded")
            
            # Handle redirect to login screen (which is common if cookie gets expired/invalid)
            if "linkedin.com/checkpoint/lg" in page.url or "login" in page.url:
                logger.warning("[LinkedinPlaywrightProvider] Redirected to login wall. Public access restricted.")
                instance.failure_count += 1
                instance.consecutive_failures += 1
                # Force delete current cookies since they caused a redirect
                bm.cookie_manager.save_cookies("linkedin.com", [])
                raise ProviderUnavailable(self.name, "LinkedIn Login redirection wall detected.")

            if response and response.status == 404:
                logger.info(f"[LinkedinPlaywrightProvider] LinkedIn page not found (HTTP 404) for: {target_url}. Returning no results.")
                instance.success_count += 1
                instance.consecutive_failures = 0
                try:
                    from pillar1.browser.browser_breaker import BrowserCircuitBreaker
                    BrowserCircuitBreaker.get_instance().record_success(self.name)
                except Exception:
                    pass
                return []

            if not response or response.status >= 400:
                instance.failure_count += 1
                instance.consecutive_failures += 1
                raise ProviderUnavailable(self.name, f"LinkedIn returned error response: {response.status if response else 'No Response'}")

            # Save updated cookies
            try:
                new_cookies = context.cookies()
                bm.cookie_manager.save_cookies("linkedin.com", new_cookies)
            except Exception as e:
                logger.warning(f"[LinkedinPlaywrightProvider] Failed to save cookies: {e}")

            html = page.content()
            
            # Check for block signature
            if "captcha" in html.lower() or "authwall" in page.url:
                instance.failure_count += 1
                instance.consecutive_failures += 1
                raise ProviderUnavailable(self.name, "LinkedIn authwall / CAPTCHA block page detected.")

            # Success path
            instance.success_count += 1
            instance.consecutive_failures = 0

            # 2. Parse details from public profile template
            soup = BeautifulSoup(html, "html.parser")
            
            # Extract Company Name
            name_el = soup.select_one("h1.top-card-layout__title, h1, .top-card-layout__entity-info h1")
            name = name_el.get_text(" ", strip=True) if name_el else urlparse(target_url).path.split("/")[-1]

            # Extract About
            about_el = soup.select_one(".about-us__description, .core-section-container__content, p.about-us__description")
            about = about_el.get_text(" ", strip=True) if about_el else ""

            # Extract other metadata grid key-values
            metadata = {}
            # Definition lists are common on public layout: <dt>Label</dt><dd>Value</dd>
            dts = soup.select("dt")
            dds = soup.select("dd")
            for dt, dd in zip(dts, dds):
                label = dt.get_text(" ", strip=True).rstrip(":").strip()
                val = dd.get_text(" ", strip=True)
                metadata[label] = val

            # Check website controls
            web_link = soup.select_one("a[data-tracking-control-name='about_website'], a[href*='http']:not([href*='linkedin.com'])")
            website = web_link.get("href") if web_link else metadata.get("Website")

            industry = metadata.get("Industry") or metadata.get("Type")
            hq = metadata.get("Headquarters") or metadata.get("HQ")
            size = metadata.get("Company size") or metadata.get("Size")

            # Public leadership/employees names (if listed on the public page)
            leaders = []
            for face in soup.select(".facepile__face, .employee-profile-card h3"):
                leaders.append(face.get_text(" ", strip=True))
                
            # Clean leadership list
            leaders = [l for l in leaders if l and not l.startswith("http")]

            # 3. Format structured snippet for downstream pipeline extraction
            snippet_parts = []
            if about:
                snippet_parts.append(f"About: {about}")
            if industry:
                snippet_parts.append(f"Industry: {industry}")
            if hq:
                snippet_parts.append(f"HQ: {hq}")
            if size:
                snippet_parts.append(f"Employees: {size}")
            if website:
                snippet_parts.append(f"Website: {website}")
            if leaders:
                snippet_parts.append(f"Leadership: {', '.join(leaders[:5])}")

            snippet = " | ".join(snippet_parts)

            result = SearchResult(
                url=target_url,
                title=name,
                snippet=snippet or "LinkedIn Profile Page",
                provider=self.name,
                source="LinkedIn",
                provider_rank=1,
                query=query,
                page=page,
                timestamp=time.time()
            )

            # Register success to local circuit breaker
            from pillar1.browser.browser_breaker import BrowserCircuitBreaker
            BrowserCircuitBreaker.get_instance().record_success(self.name)

            return [result]

        except Exception as e:
            instance.failure_count += 1
            instance.consecutive_failures += 1
            from pillar1.browser.browser_breaker import BrowserCircuitBreaker
            BrowserCircuitBreaker.get_instance().record_failure(self.name)
            logger.error(f"[LinkedinPlaywrightProvider] Scrape error: {e}")
            raise

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
            instance.active_pages = max(0, instance.active_pages - 1)
