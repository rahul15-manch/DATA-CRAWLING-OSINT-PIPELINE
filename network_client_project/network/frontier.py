import hashlib
import logging
import re
from urllib.parse import urlparse, urlunparse
from collections import defaultdict

logger = logging.getLogger(__name__)

class CrawlFrontier:
    """
    Coordinates crawling policies:
    - URL Canonicalization
    - Crawl Budget (max pages per domain)
    - Content hash duplicate detection
    """
    def __init__(self, max_pages_per_domain: int = 15):
        self.max_pages_per_domain = max_pages_per_domain
        self.visited_urls = set()
        self.seen_contents = set()
        self.domain_page_counts = defaultdict(int)

    @staticmethod
    def canonicalize_url(url: str) -> str:
        """
        Normalize url to prevent crawling the same site multiple times.
        e.g., http://www.example.com/ -> https://example.com
        """
        if not url:
            return ""
        try:
            parsed = urlparse(url.lower().strip())
            netloc = parsed.netloc
            # Remove www prefix
            if netloc.startswith("www."):
                netloc = netloc[4:]
            # Normalize scheme to https (standardize)
            scheme = "https" if parsed.scheme in ["http", "https"] else parsed.scheme
            # Remove trailing slashes and default ports
            path = parsed.path.rstrip("/")
            if not path:
                path = ""
            
            # Reconstruct URL without query fragments for duplicate page detection
            # (unless it contains important query identifiers like 'lang' or 'page')
            query = ""
            if parsed.query:
                # Keep lang/page query parameters, drop others like source/utm
                keep_params = []
                for param in parsed.query.split("&"):
                    if "=" in param:
                        k, v = param.split("=", 1)
                        if k in ["lang", "page", "id"]:
                            keep_params.append(f"{k}={v}")
                if keep_params:
                    query = "&".join(keep_params)

            return urlunparse((scheme, netloc, path, "", query, ""))
        except Exception as e:
            logger.error(f"Error canonicalizing URL '{url}': {e}")
            return url

    def should_crawl(self, url: str) -> bool:
        """Check if the URL conforms to visited restrictions and crawl budget."""
        canonical = self.canonicalize_url(url)
        if not canonical:
            return False

        if canonical in self.visited_urls:
            return False

        try:
            parsed = urlparse(canonical)
            domain = parsed.netloc
            if self.domain_page_counts[domain] >= self.max_pages_per_domain:
                logger.warning(f"[Frontier] Crawl budget exceeded for domain '{domain}' ({self.max_pages_per_domain} pages limit). Skipping {url}")
                return False
        except Exception:
            pass

        return True

    def record_crawl(self, url: str, html: str = None) -> bool:
        """
        Record a successful fetch.
        Computes text hash of html (if provided) to detect duplicate content.
        Returns True if the content is unique and successfully recorded, False if duplicate.
        """
        canonical = self.canonicalize_url(url)
        if not canonical:
            return False

        self.visited_urls.add(canonical)
        
        try:
            parsed = urlparse(canonical)
            domain = parsed.netloc
            self.domain_page_counts[domain] += 1
        except Exception:
            pass

        if html:
            text_content = re.sub(r'<[^>]+>', ' ', html)
            text_content = " ".join(text_content.split())
            content_hash = hashlib.sha256(text_content.encode('utf-8')).hexdigest()
            
            if content_hash in self.seen_contents:
                logger.info(f"[Frontier] Duplicate content detected for {url}. Skipping pipeline.")
                return False
            self.seen_contents.add(content_hash)

        return True

_frontier = CrawlFrontier()
def get_frontier() -> CrawlFrontier:
    return _frontier
