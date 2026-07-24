import logging
import numpy as np
from typing import Dict, Any
from pillar3_network_resilience.network import signals
from pillar3_network_resilience.network.exceptions import ErrorDetector

logger = logging.getLogger(__name__)

class ProviderStatsTracker:
    """
    Decoupled stats tracker that compiles search provider performance
    by listening to network signals.
    """
    def __init__(self):
        # Maps provider slug -> metrics dictionary
        self.stats: Dict[str, Dict[str, Any]] = {}
        signals.connect(self.on_request_received, signals.REQUEST_RECEIVED)
        signals.connect(self.on_request_completed, signals.REQUEST_COMPLETED)
        signals.connect(self.on_request_failed, signals.REQUEST_FAILED)

    def _get_provider_name(self, request) -> str:
        from urllib.parse import urlparse
        return request.meta.get("provider") or urlparse(request.url).netloc

    def _init_provider(self, provider: str) -> None:
        if provider not in self.stats:
            self.stats[provider] = {
                "queries": 0,
                "http_successes": 0,
                "parser_successes": 0,
                "organic_results": 0,
                "accepted_companies": 0,
                "exported_leads": 0,
                "zero_results": 0,
                "homepage_successes": 0,
                "network_failures": 0,
                "429s": 0,
                "captchas": 0,
                "timeouts": 0,
                "total_latency_ms": 0.0,
                "request_count": 0,
                "latencies_ms": []
            }

    def record_search_outcome(self, provider: str, organic_results: int = 0, accepted_companies: int = 0, exported_leads: int = 0, parser_success: bool = True, zero_results: bool = False) -> None:
        """Called by the Search Manager after parsing results."""
        self._init_provider(provider)
        stats = self.stats[provider]
        if zero_results:
            stats["zero_results"] += 1
            stats["parser_successes"] += 1 # A zero result page means the parser worked (found 0).
        elif organic_results > 0:
            stats["organic_results"] += organic_results
            stats["accepted_companies"] += accepted_companies
            stats["exported_leads"] += exported_leads
            stats["parser_successes"] += 1
        elif not parser_success:
            # We had HTTP 200, but parser failed.
            pass

    def record_homepage_success(self, provider: str, count: int = 1) -> None:
        self._init_provider(provider)
        self.stats[provider]["homepage_successes"] += count

    def on_request_received(self, request) -> None:
        provider = self._get_provider_name(request)
        self._init_provider(provider)
        self.stats[provider]["queries"] += 1

    def on_request_completed(self, request, response) -> None:
        provider = self._get_provider_name(request)
        self._init_provider(provider)
        
        stats = self.stats[provider]
        stats["request_count"] += 1
        stats["total_latency_ms"] += response.latency_ms
        stats["latencies_ms"].append(response.latency_ms)
        
        waf_error = ErrorDetector.detect_waf_or_captcha(response)
        if waf_error:
            stats["network_failures"] += 1
            err_name = waf_error.__class__.__name__.lower()
            if "429" in err_name or "rate" in err_name:
                stats["429s"] += 1
            elif "captcha" in err_name:
                stats["captchas"] += 1
        else:
            stats["http_successes"] += 1

    def on_request_failed(self, request, exception) -> None:
        provider = self._get_provider_name(request)
        self._init_provider(provider)
        stats = self.stats[provider]
        stats["network_failures"] += 1
        stats["request_count"] += 1
        
        err_str = str(exception).lower()
        if "timeout" in err_str or "timed out" in err_str:
            stats["timeouts"] += 1

    def compile_report(self) -> Dict[str, Dict[str, Any]]:
        report = {}
        for prov, metrics in self.stats.items():
            reqs = max(1, metrics["request_count"])
            lats = metrics["latencies_ms"]
            
            avg_lat = (metrics["total_latency_ms"] / reqs) / 1000.0
            med_lat = (float(np.median(lats)) / 1000.0) if lats else 0.0
            p95_lat = (float(np.percentile(lats, 95)) / 1000.0) if lats else 0.0
            
            # User defined score formula
            http_succ = metrics["http_successes"] / reqs
            parser_succ = metrics["parser_successes"] / reqs
            accepted = metrics["accepted_companies"]
            hp_succ = metrics["homepage_successes"]
            
            # Latency penalty: fast is better.
            latency_modifier = max(0, 1.0 - (avg_lat / 10.0))
            
            score = (0.50 * accepted) + (0.20 * hp_succ) + (0.15 * parser_succ) + (0.10 * http_succ) + (0.05 * latency_modifier)

            report[prov] = {
                "queries": metrics["queries"],
                "http_successes": metrics["http_successes"],
                "parser_successes": metrics["parser_successes"],
                "zero_results": metrics["zero_results"],
                "organic_results": metrics["organic_results"],
                "accepted_companies": metrics["accepted_companies"],
                "exported_leads": metrics["exported_leads"],
                "score": score,
                "network_failures": metrics["network_failures"],
                "avg_latency": avg_lat,
                "median_latency": med_lat,
                "p95_latency": p95_lat,
                "rate_429": metrics["429s"] / reqs,
                "captcha_rate": metrics["captchas"] / reqs,
                "timeout_rate": metrics["timeouts"] / reqs
            }
        return report

provider_stats = ProviderStatsTracker()
