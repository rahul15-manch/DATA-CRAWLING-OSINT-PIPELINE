import urllib.robotparser
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

class RobotsChecker:
    """
    Fetches and checks robots.txt rules for domains.
    Caches results to avoid hitting robots.txt repeatedly.
    """
    def __init__(self, user_agent: str = "*"):
        self.user_agent = user_agent
        self.parsers = {}

    def get_parser(self, domain: str) -> urllib.robotparser.RobotFileParser:
        if domain not in self.parsers:
            parser = urllib.robotparser.RobotFileParser()
            robots_url = f"https://{domain}/robots.txt"
            try:
                import requests
                headers = {"User-Agent": "FlowizBot/1.0"}
                # Try fetching directly, fallback to empty rules if failed
                resp = requests.get(robots_url, headers=headers, timeout=3.0)
                if resp.status_code == 200:
                    parser.parse(resp.text.splitlines())
                else:
                    parser.allow_all = True
            except Exception:
                parser.allow_all = True
            self.parsers[domain] = parser
        return self.parsers[domain]

    def allowed(self, url: str) -> bool:
        try:
            parsed = urlparse(url)
            domain = parsed.netloc
            parser = self.get_parser(domain)
            if getattr(parser, "allow_all", False):
                return True
            return parser.can_fetch(self.user_agent, url)
        except Exception as e:
            logger.warning(f"Error checking robots.txt for {url}: {e}")
            return True
