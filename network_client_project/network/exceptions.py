import requests
from bs4 import BeautifulSoup
from typing import Optional

# --- CUSTOM EXCEPTIONS ---
class NetworkClientError(Exception):
    """Base exception for all custom network errors."""
    pass

class ProxyBannedError(NetworkClientError):
    """Raised when the target explicitly blocks the proxy IP."""
    pass

class CaptchaDetectedError(NetworkClientError):
    """Raised when a CAPTCHA challenge is intercepted."""
    pass

class CloudflareBlockError(NetworkClientError):
    """Raised when Cloudflare IUAM or Turnstile blocks the request."""
    pass

class DatadomeBlockError(NetworkClientError):
    """Raised when Datadome WAF blocks the request."""
    pass


# --- ERROR AND WAF DETECTION ENGINE ---
class ErrorDetector:
    """
    Analyzes HTTP responses to detect soft-blocks, CAPTCHAs, and WAF intercepts.
    Sometimes a website returns a 200 OK, but the HTML is actually a CAPTCHA!
    """

    @staticmethod
    def detect_waf_or_captcha(response: requests.Response) -> Optional[Exception]:
        """
        Inspects headers and body to detect if we have been blocked.
        Returns the appropriate Exception to be raised, or None if the response is clean.
        """
        status = response.status_code
        headers = response.headers
        
        # 1. Check HTTP Status Codes
        if status in [403, 401]:
            # Often means IP Ban or invalid Headers
            # We will look deeper into headers/body to confirm
            pass
            
        if status == 429:
            # Too Many Requests - Handled by Retry Engine, but WAFs sometimes use it
            if "cf-mitigated" in headers or "cloudflare" in headers.get("server", "").lower():
                return CloudflareBlockError("Cloudflare rate limit or block detected.")

        # 2. Check Specific Headers (Datadome, PerimeterX, Akamai)
        server_header = headers.get("Server", "").lower()
        if "datadome" in server_header or "x-datadome" in headers:
            return DatadomeBlockError("Datadome WAF detected in headers.")
            
        if "AkamaiGHost" in server_header:
            if status == 403:
                return ProxyBannedError("Akamai WAF IP Block detected.")

        # 3. Check HTML Body (The "Soft Block")
        # WAFs sometimes return 200 OK or 403 Forbidden with a CAPTCHA page.
        # We only check if the content-type is HTML to save CPU.
        content_type = headers.get("Content-Type", "")
        if "text/html" in content_type:
            html = response.text.lower()
            
            # Cloudflare Turnstile / IUAM
            if "cf-browser-verification" in html or "id=\"challenge-running\"" in html:
                return CloudflareBlockError("Cloudflare JS Challenge / Captcha detected in HTML.")
                
            # Generic Captcha checks
            if "g-recaptcha" in html or "hcaptcha" in html or "px-captcha" in html:
                return CaptchaDetectedError("reCAPTCHA, hCaptcha, or PerimeterX detected in HTML.")
                
            # Common soft-ban strings
            if "access denied" in html and status == 403:
                return ProxyBannedError("Generic 'Access Denied' soft-block detected.")
                
        return None
