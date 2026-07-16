import logging
from typing import Dict, Any, List
from network_client_project.network import signals

logger = logging.getLogger(__name__)

class ProxyStatsTracker:
    """
    Decoupled stats tracker that compiles proxy performance metrics
    by listening to network signals.
    """
    def __init__(self):
        # Maps proxy raw URL -> metrics dictionary
        self.stats: Dict[str, Dict[str, Any]] = {}
        signals.connect(self.on_request_completed, signals.REQUEST_COMPLETED)
        signals.connect(self.on_request_failed, signals.REQUEST_FAILED)

    def _get_proxy_url(self, request) -> str:
        proxy_dict = request.meta.get("proxies")
        return proxy_dict.get("http") if proxy_dict else "direct"

    def _init_proxy(self, proxy_url: str) -> None:
        if proxy_url not in self.stats:
            self.stats[proxy_url] = {
                "requests": 0,
                "successes": 0,
                "failures": 0,
                "latencies_ms": []
            }

    def on_request_completed(self, request, response) -> None:
        proxy_url = self._get_proxy_url(request)
        self._init_proxy(proxy_url)
        
        stats = self.stats[proxy_url]
        stats["requests"] += 1
        
        from network_client_project.network.exceptions import ErrorDetector
        waf_error = ErrorDetector.detect_waf_or_captcha(response)
        if waf_error:
            stats["failures"] += 1
        else:
            stats["successes"] += 1
            stats["latencies_ms"].append(response.latency_ms)

    def on_request_failed(self, request, exception) -> None:
        proxy_url = self._get_proxy_url(request)
        self._init_proxy(proxy_url)
        
        stats = self.stats[proxy_url]
        stats["requests"] += 1
        stats["failures"] += 1

proxy_stats = ProxyStatsTracker()
