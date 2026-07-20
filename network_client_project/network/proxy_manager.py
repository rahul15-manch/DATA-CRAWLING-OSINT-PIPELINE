import random
import threading
import time
import logging
import json
import os
from typing import List, Optional, Dict, Tuple, Any
from dataclasses import dataclass, field
from collections import deque

from .proxy_health import (
    OutcomeType, GoogleTier,
    freshness_factor, aging_decay, compute_google_tier,
    compute_google_confidence, combined_confidence,
    recent_success_ratio, avg_latency, compute_derived_score,
    quarantine_duration, QUARANTINE_INACTIVE_AFTER, QUARANTINE_MAX_STEP,
    derived_score_cache, TIER_PRIORITY,
)

logger = logging.getLogger(__name__)

def classify_error(error: Exception | None) -> str:
    if not error:
        return "generic"
    err_str = str(error).lower()
    err_name = error.__class__.__name__.lower()
    
    if "captcha" in err_name or "captcha" in err_str: return "captcha"
    if "sorry" in err_name or "sorry" in err_str: return "sorry_page"
    if "enablejs" in err_name or "enablejs" in err_str: return "enablejs"
    if "consent" in err_name or "consent" in err_str: return "consent_page"
    if "parse" in err_name or "parse" in err_str: return "parser_failure"
    if "zero" in err_name or "zero" in err_str: return "zero_results"
    
    if any(x in err_str for x in ["certificate", "ssl cert", "local issuer", "self signed"]): return "certificate_failure"
    if "ssl" in err_str or "tls" in err_str or "handshake" in err_str: return "tls_failure"
    if "timeout" in err_str or "timed out" in err_str or "deadline" in err_str or "curl: (28)" in err_str: return "timeout"
    if any(x in err_str for x in ["connection closed", "connection reset", "connection refused", "connect failed", "proxy connect aborted", "rejected by the socks5 server", "curl: (56)", "curl: (97)"]): return "dead_connection"
    if "429" in err_str or "rate limit" in err_str or "too many requests" in err_str: return "rate_limit"
        
    return "generic"

def get_base_domain(host: str) -> str:
    host = host.lower().strip()
    if not host or host == "global":
        return "global"
    if ":" in host:
        host = host.split(":")[0]
    parts = host.split('.')
    if len(parts) >= 2:
        if parts[-2] in ("co", "com", "org", "net", "edu", "gov", "ac"):
            return ".".join(parts[-3:])
        return ".".join(parts[-2:])
    return host

# Map classify_error results to OutcomeType
_ERROR_TO_OUTCOME = {
    "captcha":              OutcomeType.GOOGLE_CAPTCHA,
    "sorry_page":           OutcomeType.GOOGLE_CAPTCHA,
    "enablejs":             OutcomeType.GOOGLE_CAPTCHA,
    "consent_page":         OutcomeType.GOOGLE_CAPTCHA,
    "rate_limit":           OutcomeType.GOOGLE_429,
    "tls_failure":          OutcomeType.TRANSPORT_TLS_ERROR,
    "certificate_failure":  OutcomeType.TRANSPORT_TLS_ERROR,
    "timeout":              OutcomeType.TRANSPORT_TIMEOUT,
    "dead_connection":      OutcomeType.TRANSPORT_CONNECTION_ERROR,
}


@dataclass
class Proxy:
    raw_url: str
    proxy_index: int = -1
    success_count: int = 0
    failure_count: int = 0
    cooldown_until: Dict[str, float] = field(default_factory=dict)
    
    google_requests: List[float] = field(default_factory=list)
    google_successes: int = 0
    google_captchas: int = 0
    google_429s: int = 0
    proxy_score: float = 100.0
    consecutive_failures: int = 0
    consecutive_blocks: Dict[str, int] = field(default_factory=dict)
    dead: bool = False
    last_used: float = 0.0
    
    google_status: str = "healthy"
    bing_status: str = "healthy"
    general_status: str = "healthy"

    # ── New fields (Phase 1) ──────────────────────────────────────────────
    last_success_ts: Optional[float] = None
    last_failure_ts: Optional[float] = None
    latency_samples: deque = field(default_factory=lambda: deque(maxlen=10))
    outcome_history: deque = field(default_factory=lambda: deque(maxlen=50))
    quarantine_until: Optional[float] = None
    quarantine_step: int = 0
    inactive: bool = False
    dead_for_google: bool = False
    dead_for_bing: bool = False
    consecutive_timeouts: Dict[str, int] = field(default_factory=dict)
    
    # Track granular stats per provider dynamically
    provider_metrics: Dict[str, Dict[str, Any]] = field(default_factory=lambda: {
        "google": {"successes": 0, "timeouts": 0, "captchas": 0, "total_requests": 0, "latencies": []},
        "bing": {"successes": 0, "timeouts": 0, "captchas": 0, "total_requests": 0, "latencies": []},
        "duckduckgo": {"successes": 0, "timeouts": 0, "captchas": 0, "total_requests": 0, "latencies": []},
        "brave": {"successes": 0, "timeouts": 0, "captchas": 0, "total_requests": 0, "latencies": []},
        "directory": {"successes": 0, "timeouts": 0, "captchas": 0, "total_requests": 0, "latencies": []},
        "general_crawl": {"successes": 0, "timeouts": 0, "captchas": 0, "total_requests": 0, "latencies": []}
    })
    provider_capabilities: Dict[str, str] = field(default_factory=lambda: {
        "google": "GOOD",
        "bing": "GOOD",
        "duckduckgo": "GOOD",
        "brave": "GOOD",
        "directory": "GOOD",
        "general_crawl": "GOOD",
    })

    def _normalize_provider_key(self, provider: Optional[str] = None, domain: Optional[str] = None) -> str:
        prov = (provider or "").lower().strip()
        dom = (domain or "").lower().strip()
        
        if "google" in prov or "google" in dom:
            return "google"
        if "bing" in prov or "bing" in dom:
            return "bing"
        if "duckduckgo" in prov or "duckduckgo" in dom or "ddg" in prov or "ddg" in dom:
            return "duckduckgo"
        if "brave" in prov or "brave" in dom:
            return "brave"
        if "directory" in prov or "directory" in dom:
            return "directory"
        return "general_crawl"

    def get_provider_capability(self, provider: Optional[str] = None) -> str:
        key = self._normalize_provider_key(provider)
        if not hasattr(self, "provider_capabilities") or self.provider_capabilities is None:
            self.provider_capabilities = {
                "google": "GOOD",
                "bing": "GOOD",
                "duckduckgo": "GOOD",
                "brave": "GOOD",
                "directory": "GOOD",
                "general_crawl": "GOOD",
            }

        if self.dead or self.inactive:
            return "blocked"
        # Only block for provider-specific quarantine (Google/Bing quarantine should NOT
        # block this proxy from serving linkedin, goodfirms, or general crawl requests).
        if key in ("google", "bing") and self.quarantine_until and time.time() < self.quarantine_until:
            return "blocked"
        if key == "google" and getattr(self, "dead_for_google", False):
            return "blocked"
        if key == "bing" and getattr(self, "dead_for_bing", False):
            return "blocked"

        return self.provider_capabilities.get(key, "GOOD").lower()

    def get_provider_score(self, domain: Optional[str] = None, provider: Optional[str] = None) -> float:
        domain_key = self._normalize_provider_key(provider=provider, domain=domain)
        
        if not hasattr(self, "provider_metrics") or self.provider_metrics is None:
            self.provider_metrics = {
                "google": {"successes": 0, "timeouts": 0, "captchas": 0, "total_requests": 0, "latencies": []},
                "bing": {"successes": 0, "timeouts": 0, "captchas": 0, "total_requests": 0, "latencies": []},
                "duckduckgo": {"successes": 0, "timeouts": 0, "captchas": 0, "total_requests": 0, "latencies": []},
                "default": {"successes": 0, "timeouts": 0, "captchas": 0, "total_requests": 0, "latencies": []}
            }
            
        metrics = self.provider_metrics.get(domain_key)
        if not metrics or metrics["total_requests"] == 0:
            return self.proxy_score
            
        reqs = metrics["total_requests"]
        succ_rate = metrics["successes"] / reqs
        timeout_rate = metrics["timeouts"] / reqs
        captcha_rate = metrics["captchas"] / reqs
        
        score = (succ_rate * 100.0) - (timeout_rate * 50.0) - (captcha_rate * 80.0)
        return max(1.0, min(100.0, score))

    @property
    def formatted(self) -> Dict[str, str]:
        url = self.raw_url if "://" in self.raw_url else f"http://{self.raw_url}"
        return {"http": url, "https": url}

    def is_cooling_down(self, domain: str = "global") -> bool:
        if self.dead:
            return True
        if self.inactive:
            return True
        base_dom = get_base_domain(domain)
        now = time.time()

        # Quarantine is set by WAF/CAPTCHA/rate-limit blocks which are search-engine specific.
        # Only enforce it when the requested domain is actually a search engine.
        # A proxy quarantined for Google should still serve LinkedIn, GoodFirms, etc.
        domain_lower = domain.lower()
        is_search_engine = "google" in domain_lower or "bing" in domain_lower or "duckduckgo" in domain_lower or "brave" in domain_lower
        if is_search_engine and self.quarantine_until and now < self.quarantine_until:
            return True

        cd_until = self.cooldown_until.get(base_dom, 0.0)
        global_cd = self.cooldown_until.get("global", 0.0)
        is_cd = (now < cd_until) or (now < global_cd)
        
        if not is_cd:
            transitioned = False
            if "google" in domain.lower() and self.google_status == "blocked":
                self.google_status = "healthy"
                if self.consecutive_blocks: self.consecutive_blocks[base_dom] = 0
                transitioned = True
            elif "bing" in domain.lower() and self.bing_status == "blocked":
                self.bing_status = "healthy"
                if self.consecutive_blocks: self.consecutive_blocks[base_dom] = 0
                transitioned = True
            elif self.general_status == "blocked":
                self.general_status = "healthy"
                if self.consecutive_blocks: self.consecutive_blocks[base_dom] = 0
                transitioned = True
                
            if transitioned:
                logger.info(f"[ProxyManager] Proxy {self.raw_url} transitioned to healthy.")
                    
        return is_cd

    def has_google_budget(self, budget: int, window_seconds: float = 600.0) -> bool:
        now = time.time()
        self.google_requests = [t for t in self.google_requests if now - t < window_seconds]
        return len(self.google_requests) < budget

    def record_google_request(self):
        self.google_requests.append(time.time())

    def _record_outcome(self, outcome: OutcomeType, latency_s: Optional[float] = None):
        """Append an outcome to the rolling history and invalidate the score cache."""
        self.outcome_history.append((time.time(), outcome))
        if latency_s is not None and latency_s > 0:
            self.latency_samples.append(latency_s)
        derived_score_cache.invalidate(self.raw_url)

    def record_success(self, domain: str = "global", reason: str = "VALID_RESULTS", latency_s: Optional[float] = None):
        self.success_count += 1
        self.failure_count = 0
        self.consecutive_failures = 0
        now = time.time()

        # Update last_success_ts immediately (no two-success requirement)
        self.last_success_ts = now

        # Update provider metrics
        domain_key = self._normalize_provider_key(provider=domain, domain=domain)
        if not hasattr(self, "provider_metrics") or self.provider_metrics is None:
            self.provider_metrics = {
                "google": {"successes": 0, "timeouts": 0, "captchas": 0, "total_requests": 0, "latencies": []},
                "bing": {"successes": 0, "timeouts": 0, "captchas": 0, "total_requests": 0, "latencies": []},
                "duckduckgo": {"successes": 0, "timeouts": 0, "captchas": 0, "total_requests": 0, "latencies": []},
                "default": {"successes": 0, "timeouts": 0, "captchas": 0, "total_requests": 0, "latencies": []}
            }
        metrics = self.provider_metrics.setdefault(domain_key, {"successes": 0, "timeouts": 0, "captchas": 0, "total_requests": 0, "latencies": []})
        metrics["total_requests"] += 1
        metrics["successes"] += 1
        if latency_s is not None:
            metrics["latencies"].append(latency_s)
        if not hasattr(self, "provider_capabilities") or self.provider_capabilities is None:
            self.provider_capabilities = {
                "google": "GOOD",
                "bing": "GOOD",
                "duckduckgo": "GOOD",
                "brave": "GOOD",
                "directory": "GOOD",
                "general_crawl": "GOOD",
            }
        status_val = "GOOD"
        if latency_s is not None and latency_s > 3.0:
            status_val = "SLOW"
        self.provider_capabilities[domain_key] = status_val

        # Clear quarantine on success
        if self.quarantine_until:
            self.quarantine_until = None
            self.quarantine_step = 0
            logger.info(f"[ProxyManager] Proxy {self.raw_url} quarantine cleared after success.")
        if self.inactive:
            self.inactive = False
            logger.info(f"[ProxyManager] Proxy {self.raw_url} reactivated after success.")
        
        base_dom = get_base_domain(domain)
        if self.consecutive_blocks:
            self.consecutive_blocks[base_dom] = 0
            
        if not hasattr(self, "consecutive_timeouts") or self.consecutive_timeouts is None:
            self.consecutive_timeouts = {}
        self.consecutive_timeouts[base_dom] = 0
        
        if "google" in domain.lower():
            self.dead_for_google = False
        elif "bing" in domain.lower():
            self.dead_for_bing = False
            
        if base_dom in self.cooldown_until: self.cooldown_until[base_dom] = 0.0
        if "global" in self.cooldown_until: self.cooldown_until["global"] = 0.0
            
        old_score = self.proxy_score
        
        # Exact Scoring Table
        # ORGANIC_RESULTS: +8
        # VALID_ZERO_RESULTS: 0
        if reason == "VALID_RESULTS":
            increment = 8.0
        elif reason == "VALID_ZERO_RESULTS":
            increment = 0.0
        else:
            increment = 0.0
            
        if "google" in domain.lower():
            self.google_successes += 1
            self.google_status = "healthy"
            self.proxy_score = min(100.0, self.proxy_score + increment)
            self._record_outcome(OutcomeType.GOOGLE_SERP, latency_s)
        elif "bing" in domain.lower():
            self.bing_status = "healthy"
            self.proxy_score = min(100.0, self.proxy_score + increment)
            self._record_outcome(OutcomeType.TRANSPORT_SUCCESS, latency_s)
        else:
            self.general_status = "healthy"
            self.proxy_score = min(100.0, self.proxy_score + increment)
            self._record_outcome(OutcomeType.TRANSPORT_SUCCESS, latency_s)
            
        score_change = self.proxy_score - old_score
        logger.info(f"[Proxy Scoring] Proxy: {self.raw_url} | Old score: {old_score:.1f} | Reason: SUCCESS ({reason}) | New score: {self.proxy_score:.1f}")
        
        if score_change > 0:
            logger.info(f"[ProxyManager] Proxy {self.raw_url} score changed by +{score_change:.1f} (Reason: {reason})")
        else:
            logger.info(f"[ProxyManager] Proxy {self.raw_url} score changed by +0.0 (Reason: {reason})")

    def record_failure(self, domain: str = "global", error: Exception | None = None, cooldown_seconds: float = 60.0, reason: str | None = None, latency_s: Optional[float] = None):
        self.failure_count += 1
        now = time.time()
        old_score = self.proxy_score
        self.last_failure_ts = now
        
        if reason:
            if reason == "CAPTCHA": err_type = "captcha"
            elif reason == "ENABLE_JS": err_type = "enablejs"
            elif reason == "CONSENT_PAGE": err_type = "consent_page"
            elif reason == "CHALLENGE_PAGE": err_type = "captcha"  # challenge/WAF wall = same as captcha
            elif reason == "RATE_LIMIT": err_type = "rate_limit"
            elif reason == "TIMEOUT": err_type = "timeout"
            elif reason in ["PARSER_FAILURE", "UNKNOWN_LAYOUT"]: err_type = "parser_failure"
            elif reason == "NETWORK_FAILURE": err_type = "dead_connection"
            else: err_type = "other"
        else:
            err_type = classify_error(error)

        # Update provider metrics
        domain_key = self._normalize_provider_key(provider=domain, domain=domain)
        if not hasattr(self, "provider_metrics") or self.provider_metrics is None:
            self.provider_metrics = {
                "google": {"successes": 0, "timeouts": 0, "captchas": 0, "total_requests": 0, "latencies": []},
                "bing": {"successes": 0, "timeouts": 0, "captchas": 0, "total_requests": 0, "latencies": []},
                "duckduckgo": {"successes": 0, "timeouts": 0, "captchas": 0, "total_requests": 0, "latencies": []},
                "default": {"successes": 0, "timeouts": 0, "captchas": 0, "total_requests": 0, "latencies": []}
            }
        metrics = self.provider_metrics.setdefault(domain_key, {"successes": 0, "timeouts": 0, "captchas": 0, "total_requests": 0, "latencies": []})
        metrics["total_requests"] += 1
        if err_type == "timeout":
            metrics["timeouts"] += 1
        elif err_type in ["captcha", "enablejs", "sorry_page", "consent_page", "rate_limit"]:
            metrics["captchas"] += 1

        if not hasattr(self, "provider_capabilities") or self.provider_capabilities is None:
            self.provider_capabilities = {
                "google": "GOOD",
                "bing": "GOOD",
                "duckduckgo": "GOOD",
                "brave": "GOOD",
                "directory": "GOOD",
                "general_crawl": "GOOD",
            }
            
        if err_type in ["captcha", "enablejs", "sorry_page", "consent_page"]:
            self.provider_capabilities[domain_key] = "CAPTCHA"
        elif err_type == "rate_limit":
            self.provider_capabilities[domain_key] = "BLOCKED"
        elif err_type == "timeout":
            self.provider_capabilities[domain_key] = "TIMEOUT"
        elif err_type in ["tls_failure", "certificate_failure"]:
            self.provider_capabilities[domain_key] = "TLS_ERROR"
        elif err_type == "dead_connection":
            self.provider_capabilities[domain_key] = "DEAD"
        else:
            self.provider_capabilities[domain_key] = self.provider_capabilities.get(domain_key, "GOOD")
        
        # Record layered outcome
        outcome = _ERROR_TO_OUTCOME.get(err_type)
        if outcome:
            self._record_outcome(outcome, latency_s)
        elif err_type == "parser_failure":
            self._record_outcome(OutcomeType.PARSER_FAILURE, latency_s)
        
        # Exact Scoring Table implementation
        penalty = 0.0
        if err_type == "parser_failure":
            penalty = 2.0
        elif err_type == "captcha":
            penalty = 10.0
        elif err_type == "rate_limit":
            penalty = 8.0
        elif err_type == "timeout":
            penalty = 5.0
        elif err_type in ["dead_connection", "tls_failure", "certificate_failure"]:
            penalty = 6.0
        else:
            # Default fallback for unlisted blocks (e.g. consent pages or enables js)
            penalty = 5.0

        if err_type in ["parser_failure", "zero_results"]:
            # Note: The table asks for parser_failure to be -2, and zero_results should be neutral (0)
            if err_type == "zero_results":
                logger.info(f"[ProxyManager] Proxy {self.raw_url} score changed by +0.0 (Reason: {reason or err_type.upper()})")
                return
            else:
                self.proxy_score = max(0.0, self.proxy_score - penalty)
                logger.info(f"[ProxyManager] Proxy {self.raw_url} score changed by -{penalty:.1f} (Reason: PARSER_FAILURE)")
                return

        is_block = err_type in ["captcha", "enablejs", "sorry_page", "consent_page", "rate_limit"]
        
        base_dom = get_base_domain(domain)

        if is_block:
            self.consecutive_failures = 0
            
            if self.consecutive_blocks is None: self.consecutive_blocks = {}
            current_blocks = self.consecutive_blocks.get(base_dom, 0) + 1
            self.consecutive_blocks[base_dom] = current_blocks
            
            # Use quarantine with exponential backoff instead of fixed cooldown
            self.quarantine_step = min(self.quarantine_step + 1, QUARANTINE_MAX_STEP + QUARANTINE_INACTIVE_AFTER)
            qd = quarantine_duration(self.quarantine_step)
            
            # Apply strict long cooldowns specifically for Google domains
            if "google" in domain.lower():
                from .config import config
                if err_type == "rate_limit":
                    qd = max(qd, getattr(config, "GOOGLE_429_COOLDOWN", 900.0))
                else:
                    qd = max(qd, getattr(config, "GOOGLE_CAPTCHA_COOLDOWN", 1800.0))

            self.quarantine_until = now + qd
            
            # Mark inactive after too many consecutive backoffs at the cap
            if self.quarantine_step > QUARANTINE_MAX_STEP + QUARANTINE_INACTIVE_AFTER:
                self.inactive = True
                logger.warning(f"[ProxyManager] Proxy {self.raw_url} marked INACTIVE after repeated quarantine failures.")
            
            if err_type == "rate_limit":
                if "google" in domain.lower():
                    self.google_429s += 1
            else:
                if "google" in domain.lower():
                    self.google_captchas += 1
            
            self.proxy_score = max(0.0, self.proxy_score - penalty)
            if self.proxy_score < 60.0:
                if "google" in domain.lower():
                    self.google_status = "blocked"
                elif "bing" in domain.lower():
                    self.bing_status = "blocked"
                    
            # Cooldown scoped to base domain only (WAF/rate-limit is site-specific)
            self.cooldown_until[base_dom] = now + qd

            logger.info(f"[ProxyManager] Proxy {self.raw_url} quarantined for {qd:.0f}s (step {self.quarantine_step}) for domain {base_dom}. Score changed by -{penalty:.1f}.")
            
        elif err_type in ["dead_connection", "tls_failure", "certificate_failure", "timeout"]:
            self.consecutive_failures += 1
            self.proxy_score = max(0.0, self.proxy_score - penalty)
            logger.info(f"[ProxyManager] Proxy {self.raw_url} connection failed (step {self.consecutive_failures}). Score changed by -{penalty:.1f}.")

            if not hasattr(self, "consecutive_timeouts") or self.consecutive_timeouts is None:
                self.consecutive_timeouts = {}
            self.consecutive_timeouts[base_dom] = self.consecutive_timeouts.get(base_dom, 0) + 1

            if self.consecutive_failures > 3:
                self.dead = True
                self.proxy_score = 0.0
                logger.warning(f"[ProxyManager] Proxy {self.raw_url} marked DEAD after {self.consecutive_failures} failures.")
            else:
                # Cooldown is domain-specific ONLY — a timeout on one target site should NOT
                # block this proxy from serving LinkedIn, GoodFirms, or any other domain.
                self.cooldown_until[base_dom] = now + cooldown_seconds

            # Per-domain consecutive timeouts => mark dead for that domain only
            if self.consecutive_timeouts[base_dom] >= 3:
                if "bing" in domain.lower():
                    self.dead_for_bing = True
                    logger.warning(f"[ProxyManager] Proxy {self.raw_url} marked dead_for_bing after 3 consecutive timeouts.")
                elif "google" in domain.lower():
                    self.dead_for_google = True
                    logger.warning(f"[ProxyManager] Proxy {self.raw_url} marked dead_for_google after 3 consecutive timeouts.")
            
        else:
            self.consecutive_failures += 1
            self.proxy_score = max(0.0, self.proxy_score - 5.0)
            # Domain-specific cooldown only (same reasoning — generic error on target != global block)
            self.cooldown_until[base_dom] = now + cooldown_seconds

        # Permanent death condition based on proxy score
        if self.proxy_score <= 0.0 and not self.dead:
            self.dead = True
            logger.warning(f"[ProxyManager] Proxy {self.raw_url} marked DEAD due to score dropping to 0.0 (Reason: {reason or err_type.upper()}).")

        score_change = self.proxy_score - old_score
        logger.info(f"[Proxy Scoring] Proxy: {self.raw_url} | Old score: {old_score:.1f} | Reason: FAILURE ({reason or err_type.upper()}) | New score: {self.proxy_score:.1f}")
        logger.info(f"[ProxyManager] Proxy {self.raw_url} score changed by {score_change:.1f} (Reason: {reason or err_type.upper()})")

    # ── Tier & Derived Score ──────────────────────────────────────────────

    def get_google_tier(self) -> GoogleTier:
        """Compute Google tier dynamically from recent outcomes."""
        return compute_google_tier(self.outcome_history)

    def get_derived_score(self) -> float:
        """Get the derived scheduling score (cached)."""
        cached = derived_score_cache.get(self.raw_url)
        if cached is not None:
            return cached

        google_conf = compute_google_confidence(self.outcome_history)
        google_outcomes_count = sum(
            1 for _, ot in self.outcome_history
            if ot in (OutcomeType.GOOGLE_SERP, OutcomeType.GOOGLE_CAPTCHA,
                      OutcomeType.GOOGLE_429, OutcomeType.GOOGLE_TIMEOUT)
        )
        score = compute_derived_score(
            google_confidence=google_conf,
            proxy_score=self.proxy_score,
            observation_count=google_outcomes_count,
            last_success_ts=self.last_success_ts,
            outcome_history=self.outcome_history,
            latency_samples=self.latency_samples,
            last_used_ts=self.last_used if self.last_used > 0 else None,
        )
        derived_score_cache.put(self.raw_url, score)
        return score


class ProxyManager:
    def __init__(self):
        self._proxies: List[Proxy] = []
        self._lock = threading.Lock()
        self._sticky_sessions: Dict[str, Proxy] = {}
        self._last_successful_proxy_idx = -1
        self._state_loaded = False
        self._background_validation_started = False

    def load_from_list(self, proxy_list: List[str]):
        with self._lock:
            existing_urls = {p.raw_url for p in self._proxies}
            for p_str in proxy_list:
                if p_str not in existing_urls:
                    self._proxies.append(Proxy(raw_url=p_str, proxy_index=len(self._proxies)))
        logger.info(f"Loaded {len(proxy_list)} proxies into the manager.")
        if not self._state_loaded:
            self.load_state("proxy_state.json")

        # Trigger real-time startup background health verification
        self.validate_all_proxies_async()
        
        # Block for at most 3 seconds or until at least one proxy is verified healthy
        start_wait = time.time()
        while time.time() - start_wait < 3.0:
            with self._lock:
                healthy_count = sum(1 for p in self._proxies if not p.dead)
            if healthy_count > 0:
                break
            time.sleep(0.1)

    def validate_all_proxies_async(self):
        """Run a background thread to validate HTTPS and Google connectivity for all loaded proxies."""
        def _check_all():
            logger.info("[ProxyManager] Starting background proxy validation thread...")
            with self._lock:
                proxies_to_test = list(self._proxies)
                
            from concurrent.futures import ThreadPoolExecutor
            try:
                from curl_cffi import requests
                has_curl_cffi = True
            except ImportError:
                try:
                    import requests
                    has_curl_cffi = False
                except ImportError:
                    logger.warning("[ProxyManager] No requests or curl_cffi installed. Skipping active validation.")
                    return
            
            # Multiple test endpoints — try in order, pass if ANY succeeds
            GENERAL_TEST_URLS = [
                "https://httpbin.org/ip",
                "https://api.ipify.org",
                "https://ifconfig.me/ip",
            ]
            
            def _test_single_proxy(p: Proxy):
                url = p.raw_url if "://" in p.raw_url else f"http://{p.raw_url}"
                proxies_dict = {"http": url, "https": url}
                
                # Test Stage 1: general HTTPS — try multiple endpoints, pass on first success
                general_alive = False
                for test_url in GENERAL_TEST_URLS:
                    try:
                        if has_curl_cffi:
                            resp = requests.get(
                                test_url,
                                proxies=proxies_dict,
                                timeout=8,
                                impersonate="chrome124",
                                verify=False
                            )
                        else:
                            resp = requests.get(
                                test_url,
                                proxies=proxies_dict,
                                timeout=8,
                                verify=False
                            )
                        if resp.status_code == 200:
                            general_alive = True
                            break
                    except Exception:
                        pass  # Try next endpoint
                
                if general_alive:
                    p.dead = False
                    p.general_status = "healthy"
                    logger.info(f"[ProxyManager] Proxy {p.raw_url} -> ALIVE (general HTTPS OK)")
                else:
                    p.dead = True
                    p.general_status = "dead"
                    # Do NOT zero the score — keep historical score intact
                    # Score reflects past performance; dead flag blocks current use
                    logger.warning(f"[ProxyManager] Proxy {p.raw_url} -> DEAD (all {len(GENERAL_TEST_URLS)} general HTTPS tests failed)")
                    return
                    
                # Test Stage 2: Google HTTPS (only if general is alive)
                try:
                    if has_curl_cffi:
                        resp = requests.get(
                            "https://www.google.com",
                            proxies=proxies_dict,
                            timeout=8,
                            impersonate="chrome124",
                            verify=False
                        )
                    else:
                        resp = requests.get(
                            "https://www.google.com",
                            proxies=proxies_dict,
                            timeout=8,
                            verify=False
                        )
                    if resp.status_code == 200:
                        p.google_status = "healthy"
                        p.dead_for_google = False
                        logger.info(f"[ProxyManager] Proxy {p.raw_url} -> Google OK")
                    elif resp.status_code == 429:
                        p.google_status = "blocked"
                        p.cooldown_until["www.google.com"] = time.time() + 900.0
                        logger.warning(f"[ProxyManager] Proxy {p.raw_url} -> Google 429 (15min cooldown)")
                    else:
                        p.google_status = "blocked"
                        logger.warning(f"[ProxyManager] Proxy {p.raw_url} -> Google HTTP {resp.status_code}")
                except Exception as e:
                    p.google_status = "blocked"
                    p.dead_for_google = True
                    logger.warning(f"[ProxyManager] Proxy {p.raw_url} -> Google UNREACHABLE ({e})")
                    
            with ThreadPoolExecutor(max_workers=min(15, len(proxies_to_test) or 1)) as executor:
                executor.map(_test_single_proxy, proxies_to_test)
                
            alive = sum(1 for p in proxies_to_test if not p.dead)
            google_alive = sum(1 for p in proxies_to_test if not p.dead and not p.dead_for_google)
            logger.info(f"[ProxyManager] Background proxy validation complete. Alive: {alive}/{len(proxies_to_test)}, Google-capable: {google_alive}/{len(proxies_to_test)}")
            
        threading.Thread(target=_check_all, name="ProxyManager-StartupValidator", daemon=True).start()

    def load_from_file(self, filepath: str):
        try:
            with open(filepath, 'r') as f:
                proxies = [line.strip() for line in f if line.strip()]
            self.load_from_list(proxies)
        except Exception as e:
            logger.error(f"Failed to load proxies from file: {e}")

    def save_state(self, filepath: str, is_atexit: bool = False):
        try:
            state = {}
            with self._lock:
                for p in self._proxies:
                    # Serialize outcome_history as list of [timestamp, outcome_str]
                    outcome_list = [[ts, ot if isinstance(ot, str) else ot.value] for ts, ot in p.outcome_history]
                    latency_list = list(p.latency_samples)

                    state[p.raw_url] = {
                        "score": p.proxy_score,
                        "google_successes": p.google_successes,
                        "google_captchas": p.google_captchas,
                        "google_429s": p.google_429s,
                        "consecutive_failures": p.consecutive_failures,
                        "consecutive_blocks": p.consecutive_blocks,
                        "dead": p.dead,
                        "google_status": p.google_status,
                        "bing_status": p.bing_status,
                        "general_status": p.general_status,
                        # New fields
                        "last_success_ts": p.last_success_ts,
                        "last_failure_ts": p.last_failure_ts,
                        "latency_samples": latency_list,
                        "outcome_history": outcome_list,
                        "quarantine_until": p.quarantine_until,
                        "quarantine_step": p.quarantine_step,
                        "inactive": p.inactive,
                        "dead_for_google": p.dead_for_google,
                        "dead_for_bing": p.dead_for_bing,
                        "consecutive_timeouts": p.consecutive_timeouts,
                        "provider_capabilities": p.provider_capabilities,
                    }
            with open(filepath, 'w') as f:
                json.dump(state, f, indent=2)
            if not is_atexit:
                logger.info(f"Saved proxy state to {filepath}")
                self._log_proxy_stats("Saved proxy state")
            else:
                print(f"[ProxyManager] Saved proxy state to {filepath} at process exit.")
        except Exception as e:
            if not is_atexit:
                logger.error(f"Failed to save proxy state: {e}")
            else:
                print(f"[ProxyManager] Failed to save proxy state on exit: {e}")

    def load_state(self, filepath: str):
        try:
            if not os.path.exists(filepath):
                self._state_loaded = True
                return
            with open(filepath, 'r') as f:
                state = json.load(f)
            with self._lock:
                proxy_map = {p.raw_url: p for p in self._proxies}
                for raw_url, data in state.items():
                    if raw_url in proxy_map:
                        p = proxy_map[raw_url]
                        p.proxy_score = min(100.0, data.get("score", 100.0))
                        p.google_successes = data.get("google_successes", 0)
                        p.google_captchas = data.get("google_captchas", 0)
                        p.google_429s = data.get("google_429s", 0)
                        p.consecutive_failures = data.get("consecutive_failures", 0)
                        p.consecutive_blocks = data.get("consecutive_blocks", {})
                        p.dead = data.get("dead", False)
                        p.google_status = data.get("google_status", "healthy")
                        p.bing_status = data.get("bing_status", "healthy")
                        p.general_status = data.get("general_status", "healthy")
                        # New fields — backward-compatible defaults
                        p.last_success_ts = data.get("last_success_ts", None)
                        p.last_failure_ts = data.get("last_failure_ts", None)
                        p.quarantine_until = data.get("quarantine_until", None)
                        p.quarantine_step = data.get("quarantine_step", 0)
                        p.inactive = data.get("inactive", False)
                        p.dead_for_google = data.get("dead_for_google", False)
                        p.dead_for_bing = data.get("dead_for_bing", False)
                        p.consecutive_timeouts = data.get("consecutive_timeouts", {})
                        p.provider_capabilities = data.get("provider_capabilities", {
                            "google": "unknown",
                            "bing": "unknown",
                            "duckduckgo": "unknown",
                            "default": "unknown",
                        })
                        # Restore latency_samples
                        lat_data = data.get("latency_samples", [])
                        p.latency_samples = deque(lat_data, maxlen=10)
                        # Restore outcome_history
                        oh_data = data.get("outcome_history", [])
                        restored = deque(maxlen=50)
                        for entry in oh_data:
                            if isinstance(entry, list) and len(entry) == 2:
                                ts, ot_str = entry
                                try:
                                    ot = OutcomeType(ot_str)
                                except ValueError:
                                    continue
                                restored.append((ts, ot))
                        p.outcome_history = restored
                        
                        # Reset temporary blocks/dead status from previous runs on new pipeline startup
                        p.dead = False
                        p.dead_for_google = False
                        p.dead_for_bing = False
                        p.cooldown_until.clear()
                        p.quarantine_until = None
                        p.quarantine_step = 0
                        p.inactive = False
                        if p.proxy_score <= 0.0:
                            p.proxy_score = 100.0
                            
            self._state_loaded = True
            logger.info(f"Loaded proxy state from {filepath}")
            self._log_proxy_stats("Loaded proxy state")
        except Exception as e:
            logger.error(f"Failed to load proxy state: {e}")

    def refresh_proxy_capabilities(self):
        """Re-open proxies that have cooled down and refresh capability state."""

        now = time.time()
        with self._lock:
            for proxy in self._proxies:
                if proxy.quarantine_until and now >= proxy.quarantine_until:
                    proxy.quarantine_until = None
                    proxy.quarantine_step = 0
                if proxy.inactive and proxy.last_failure_ts and now - proxy.last_failure_ts > 900:
                    proxy.inactive = False
                for key, value in list(proxy.provider_capabilities.items()):
                    if value == "blocked" and not proxy.is_cooling_down(key):
                        proxy.provider_capabilities[key] = "unknown"

    def start_background_validation(self):
        """Start a lightweight daemon that periodically refreshes proxy state."""

        if self._background_validation_started:
            return

        from .config import config
        interval = float(getattr(config, "PROXY_VALIDATION_INTERVAL_SECONDS", 300.0))

        def _loop():
            while True:
                time.sleep(interval)
                if getattr(self, "is_crawling", False):
                    logger.info("[ProxyManager] Skipping background proxy validation during active crawling.")
                    continue
                try:
                    self.refresh_proxy_capabilities()
                    self.clear_invalid_cooldowns()
                    self.validate_all_proxies_async()
                except Exception:
                    logger.exception("[ProxyManager] Background validation failed")

        thread = threading.Thread(target=_loop, name="proxy-validation", daemon=True)
        thread.start()
        self._background_validation_started = True

    def _log_proxy_stats(self, title: str):
        import sys
        if hasattr(sys, "is_finalizing") and sys.is_finalizing():
            return
        scores = sorted([(p.raw_url, p.proxy_score) for p in self._proxies], key=lambda x: x[1], reverse=True)
        non_zero = [s for s in scores if s[1] > 0]
        avg_score = sum(s[1] for s in scores) / len(scores) if scores else 0
        
        logger.info(f"[ProxyManager] {title}")
        logger.info(f"  Total non-zero: {len(non_zero)} | Average score: {avg_score:.1f}")
        logger.info("  Top 5 by score:")
        for url, score in scores[:5]:
            logger.info(f"    {url} = {score:.1f}")
        logger.info("  Bottom 5 by score:")
        for url, score in scores[-5:]:
            logger.info(f"    {url} = {score:.1f}")

    def mark_successful(self, proxy: Proxy):
        with self._lock:
            if proxy.proxy_index >= 0:
                self._last_successful_proxy_idx = proxy.proxy_index

    def clear_invalid_cooldowns(self):
        """Cleanup any cooldowns that have expired but weren't removed."""
        now = time.time()
        for proxy in self._proxies:
            expired = [d for d, t in proxy.cooldown_until.items() if now > t]
            for d in expired:
                del proxy.cooldown_until[d]

    def remove_bad_proxies(self, max_failures: int = 5):
        """Remove proxies whose failure count has crossed a hard threshold."""
        with self._lock:
            self._proxies = [p for p in self._proxies if not (p.dead or p.failure_count >= max_failures)]
            for idx, proxy in enumerate(self._proxies):
                proxy.proxy_index = idx
            self._sticky_sessions = {
                session_id: proxy
                for session_id, proxy in self._sticky_sessions.items()
                if proxy in self._proxies
            }

    def get_healthy_count(self, domain: str = "global", budget: int = None) -> int:
        count = 0
        with self._lock:
            for p in self._proxies:
                if p.dead or p.inactive or p.is_cooling_down(domain):
                    continue
                if budget is not None and "google" in domain.lower():
                    if not p.has_google_budget(budget):
                        continue
                count += 1
        return count

    def get_proxy(self, session_id: Optional[str] = None, domain: str = "global", exclude_urls: Optional[set] = None, provider: Optional[str] = None) -> Optional[Proxy]:
        if exclude_urls is None:
            exclude_urls = set()

        domain_lower = domain.lower()
        domain_key = Proxy._normalize_provider_key(self, provider=provider, domain=domain)

        from .config import config
        intervals = getattr(config, "MIN_REUSE_INTERVALS", {"google": 15.0, "bing": 3.0, "default": 0.0})
        min_reuse = intervals.get(domain_key, 0.0)

        is_google = "google" in domain_lower

        with self._lock:
            if not self._proxies:
                return None

            if session_id and not exclude_urls:
                if session_id in self._sticky_sessions:
                    proxy = self._sticky_sessions[session_id]
                    is_healthy = not proxy.dead and not proxy.inactive and not proxy.is_cooling_down(domain)
                    if is_google and is_healthy:
                        budget = getattr(config, "GOOGLE_REQUEST_BUDGET", 6)
                        is_healthy = proxy.has_google_budget(budget)
                    if is_healthy:
                        return proxy

            now = time.time()

            # Build candidate list (filter dead, inactive, quarantined, cooling)
            healthy_candidates = []
            for p in self._proxies:
                if p.raw_url in exclude_urls or p.dead or p.inactive or p.is_cooling_down(domain):
                    continue
                if is_google and getattr(p, "dead_for_google", False):
                    continue
                if "bing" in domain_lower and getattr(p, "dead_for_bing", False):
                    continue
                if p.get_provider_capability(provider or domain) == "blocked":
                    continue
                # Check quarantine
                if p.quarantine_until and now < p.quarantine_until:
                    continue
                if is_google:
                    budget = getattr(config, "GOOGLE_REQUEST_BUDGET", 6)
                    if not p.has_google_budget(budget):
                        continue
                healthy_candidates.append(p)

            if not healthy_candidates:
                print(f"[ProxyManager] No healthy proxies available for {domain}!\n")
                return None

            # Apply min reuse interval
            fresh_candidates = [p for p in healthy_candidates if now - p.last_used >= min_reuse]
            final_candidates = fresh_candidates if fresh_candidates else healthy_candidates

            if is_google:
                # ── Tier-based selection for Google ────────────────────────
                # Group by dynamic tier
                tier_buckets: Dict[GoogleTier, List[Proxy]] = {}
                for p in final_candidates:
                    tier = p.get_google_tier()
                    tier_buckets.setdefault(tier, []).append(p)

                # Select from highest tier first
                selected = None
                for tier in [GoogleTier.A, GoogleTier.B, GoogleTier.C, GoogleTier.D, GoogleTier.E]:
                    bucket = tier_buckets.get(tier, [])
                    if bucket:
                        # Weighted random within the tier using derived_score
                        weights = [p.get_derived_score() for p in bucket]
                        selected = random.choices(bucket, weights=weights, k=1)[0]
                        logger.info(
                            f"[ProxyManager] Selected proxy {selected.raw_url} "
                            f"(Tier {tier.value}, derived={selected.get_derived_score():.3f}, "
                            f"score={selected.proxy_score:.1f}, "
                            f"freshness={freshness_factor(selected.last_success_ts):.1f})"
                        )
                        break

                if not selected:
                    print(f"[ProxyManager] No healthy proxies available for {domain}!\n")
                    return None
            else:
                # Non-Google: use original cursor-based + score weighting
                start_idx = (self._last_successful_proxy_idx + 1) % len(self._proxies) if self._proxies else 0
                # Re-sort by cursor order for non-Google
                window = final_candidates[:5]
                weights = [max(0.1, p.get_provider_score(domain=domain, provider=provider)) for p in window]
                selected = random.choices(window, weights=weights, k=1)[0]

            selected.last_used = now

            if session_id and not exclude_urls:
                self._sticky_sessions[session_id] = selected

            return selected

    def set_sticky_proxy(self, session_id: str, proxy: Proxy):
        with self._lock:
            self._sticky_sessions[session_id] = proxy

    def get_stats(self, domain: str = "global") -> Dict:
        with self._lock:
            total = len(self._proxies)
            cooling = sum(1 for p in self._proxies if p.is_cooling_down(domain))
            dead = sum(1 for p in self._proxies if p.dead)
            inactive = sum(1 for p in self._proxies if p.inactive)
            quarantined = sum(1 for p in self._proxies if p.quarantine_until and time.time() < p.quarantine_until)
            return {
                "total": total,
                "healthy": total - cooling - dead - inactive,
                "cooling_down": cooling,
                "dead": dead,
                "inactive": inactive,
                "quarantined": quarantined,
            }

    def get_proxy_by_url(self, raw_url: str) -> Optional[Proxy]:
        """Returns the Proxy object for the given raw_url."""
        with self._lock:
            for p in self._proxies:
                if p.raw_url == raw_url or p.formatted["http"] == raw_url:
                    return p
        return None

    def reward_proxy(self, raw_url: str, points: float, reason: str = "REWARD"):
        """Add granular reward points to a proxy."""
        p = self.get_proxy_by_url(raw_url)
        if p:
            old_score = p.proxy_score
            p.proxy_score = min(100.0, p.proxy_score + points)
            logger.info(f"[Proxy Scoring] Proxy: {p.raw_url} | Old score: {old_score:.1f} | Reason: {reason} | New score: {p.proxy_score:.1f}")


# ─────────────────────────────────────────────────────────────────────────────
# Global Singleton Factory
# ─────────────────────────────────────────────────────────────────────────────
_proxy_manager: ProxyManager | None = None

def get_proxy_manager() -> ProxyManager:
    """Return the global ProxyManager singleton."""
    global _proxy_manager
    if _proxy_manager is None:
        _proxy_manager = ProxyManager()
        _proxy_manager.start_background_validation()
    return _proxy_manager

# ── Signal Receivers for Decoupled Proxy Scoring ──────────────────────────────
from . import signals

def _on_request_completed(request, response):
    proxy = request.meta.get("_proxy_obj")
    if proxy and request.meta.get("auto_score", True):
        from urllib.parse import urlparse
        domain = urlparse(request.url).netloc
        
        from .exceptions import ErrorDetector
        waf_error = ErrorDetector.detect_waf_or_captcha(response)
        if waf_error:
            from .exceptions import CaptchaDetectedError, CloudflareBlockError, DatadomeBlockError
            if isinstance(waf_error, (CaptchaDetectedError, CloudflareBlockError, DatadomeBlockError)):
                proxy.record_failure(domain=domain, error=waf_error, cooldown_seconds=300)
            else:
                proxy.record_failure(domain=domain, error=waf_error)
        else:
            proxy.record_success(domain=domain, reason="VALID_RESULTS", latency_s=response.latency_ms / 1000.0)

def _on_request_failed(request, exception):
    proxy = request.meta.get("_proxy_obj")
    if proxy and request.meta.get("auto_score", True):
        from urllib.parse import urlparse
        domain = urlparse(request.url).netloc
        proxy.record_failure(domain=domain, error=exception)

signals.connect(_on_request_completed, signals.REQUEST_COMPLETED)
signals.connect(_on_on_request_failed if False else _on_request_failed, signals.REQUEST_FAILED)