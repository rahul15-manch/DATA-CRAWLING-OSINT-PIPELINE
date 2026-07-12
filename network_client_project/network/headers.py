import random
from typing import Dict, Optional

class HeaderManager:
    """
    Generates realistic, ordered HTTP headers that mimic modern browsers.
    """
    
    @staticmethod
    def get_base_headers(user_agent: str) -> Dict[str, str]:
        """
        Generates the standard headers sent by almost all browsers on a GET request.
        Note: In Python dictionaries (from Python 3.7+), insertion order is preserved.
        This is critical because some WAFs fingerprint header ordering.
        """
        return {
            "Host": "",  # To be filled dynamically based on the URL
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": random.choice([
                "en-US,en;q=0.9",
                "en-GB,en;q=0.9,en-US;q=0.8",
                "en-US,en;q=0.9,fr;q=0.8",
            ]),
        }

    @staticmethod
    def get_sec_ch_ua_headers(is_mobile: bool = False, chrome_version: str = "121") -> Dict[str, str]:
        """
        Generates modern Chromium Client Hint headers.
        These are mandatory for bypassing Cloudflare and Datadome if you claim to be Chrome.
        """
        # The 'Grease' pattern: Browsers intentionally send a randomized brand 
        # to ensure servers don't hardcode specific browser names.
        grease_brand = f'"Chromium";v="{chrome_version}", "Not-A.Brand";v="99", "Google Chrome";v="{chrome_version}"'
        
        return {
            "sec-ch-ua": grease_brand,
            "sec-ch-ua-mobile": "?1" if is_mobile else "?0",
            "sec-ch-ua-platform": '"Android"' if is_mobile else '"Windows"',
        }

    @staticmethod
    def get_sec_fetch_headers(mode: str = "navigate", dest: str = "document", site: str = "none") -> Dict[str, str]:
        """
        Generates Sec-Fetch headers indicating how and why the request was made.
        """
        # For a standard top-level page visit:
        # mode=navigate, dest=document, site=none, user=?1
        # For an AJAX/API request (XHR):
        # mode=cors, dest=empty, site=same-origin
        
        headers = {
            "Sec-Fetch-Site": site,
            "Sec-Fetch-Mode": mode,
            "Sec-Fetch-Dest": dest,
        }
        
        if mode == "navigate":
            headers["Sec-Fetch-User"] = "?1"
            
        return headers

    def generate_browser_headers(self, target_url: str, user_agent: str, is_mobile: bool = False, is_xhr: bool = False) -> Dict[str, str]:
        """
        Assembles a complete, ordered dictionary of headers for a request.
        """
        from urllib.parse import urlparse
        domain = urlparse(target_url).netloc

        # 1. Base Headers
        headers = self.get_base_headers(user_agent)
        headers["Host"] = domain

        # 2. Modern Chromium Client Hints (Only add if UA contains Chrome)
        if "Chrome" in user_agent:
            # Extract major version roughly (e.g. Chrome/121.0.0.0 -> 121)
            try:
                version = user_agent.split("Chrome/")[1].split(".")[0]
            except IndexError:
                version = "121"
                
            headers.update(self.get_sec_ch_ua_headers(is_mobile, version))

        # 3. Fetch Metadata
        if is_xhr:
            # Emulate an API/AJAX call
            headers["Accept"] = "application/json, text/plain, */*"
            headers.update(self.get_sec_fetch_headers(mode="cors", dest="empty", site="same-origin"))
            # XHR requests usually drop Upgrade-Insecure-Requests
            headers.pop("Upgrade-Insecure-Requests", None) 
        else:
            # Emulate a standard URL bar navigation
            headers.update(self.get_sec_fetch_headers(mode="navigate", dest="document", site="none"))

        return headers
