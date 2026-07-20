import threading
import time
import random
import logging
from collections import deque
from network_client_project.network.proxy_health import OutcomeType
from typing import List
from concurrent.futures import ThreadPoolExecutor
import config
from search.result import SearchResult
from search.exceptions import (
    ProviderUnavailable, ProviderParseError,
    CaptchaDetectedError, EnableJSDetectedError,
    ConsentPageDetectedError, GoogleSorryPageDetectedError
)

logger = logging.getLogger(__name__)

# Statuses that count as real failures for the circuit breaker
_CIRCUIT_BREAKER_FAIL_STATUSES = frozenset({
    "CAPTCHA", "ENABLE_JS", "RATE_LIMIT", "NETWORK_FAILURE", "CONSENT_PAGE"
})

# Statuses that mean we should rotate proxy and retry
_RETRYABLE_STATUSES = frozenset({
    "CAPTCHA", "ENABLE_JS", "RATE_LIMIT", "NETWORK_FAILURE",
})

# Statuses that mean the page was valid but parsers couldn't extract results
_PARSER_FAIL_STATUSES = frozenset({
    "PARSER_FAILURE", "UNKNOWN_LAYOUT",
})


def get_query_expectation_score(query: str) -> float:
    """Calculate query expectation score between 0.0 and 1.0.
    - Generic/location queries (e.g. 'hardware software company'): 1.0
    - Platform searches (e.g. 'site:linkedin.com/company python Noida'): 0.6
    - Specific quoted/exclusion dorks (e.g. 'site:clutch.co "AI"'): 0.2
    """
    query_lower = (query or "").lower()
    words = query_lower.split()
    if "site:" not in query_lower and len(words) <= 4:
        return 1.0
    if "site:" in query_lower and '"' not in query_lower and len(words) <= 5:
        return 0.6
    return 0.2


class GoogleRequestScheduler:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        with self._lock:
            if self._initialized:
                return

            self.max_concurrent = getattr(config, "GOOGLE_MAX_CONCURRENT", 2)
            self._executor = ThreadPoolExecutor(
                max_workers=self.max_concurrent,
                thread_name_prefix="GoogleSchedulerWorker"
            )

            # ── Failure-ratio circuit breaker ─────────────────────────────────
            _window_size = getattr(config, "GOOGLE_CB_WINDOW_SIZE", 20)
            _fail_threshold = getattr(config, "GOOGLE_CB_FAIL_THRESHOLD", 0.8)
            self._outcome_window: deque = deque(maxlen=_window_size)
            self._cb_fail_threshold = _fail_threshold
            self._circuit_open_until = 0.0
            self._circuit_breaker_opens = 0  

            # Probe & Backoff
            self._backoff_step = 0
            self._backoff_sequence = [
                getattr(config, "GOOGLE_CB_OPEN_SECONDS", 60),
                120, 300, 600
            ]
            self._probe_mode = False
            self._probe_successes = 0

            logger.info(f"[GoogleScheduler] Initialized with max_workers={self.max_concurrent}, "
                        f"circuit breaker window={_window_size}, threshold={_fail_threshold:.0%}")
            self._initialized = True

    # ── Circuit Breaker Helpers ───────────────────────────────────────────────

    def _is_circuit_open(self) -> bool:
        """Returns True if the circuit breaker is currently open."""
        if time.time() < self._circuit_open_until:
            return True
        elif self._circuit_open_until > 0 and not self._probe_mode:
            # We just passed the circuit open time
            self._probe_mode = True
            self._probe_successes = 0
            logger.info("[GoogleScheduler] Circuit Breaker cooldown expired. Entering PROBE mode.")
        return False

    def _open_circuit(self):
        open_seconds = self._backoff_sequence[min(self._backoff_step, len(self._backoff_sequence) - 1)]
        self._circuit_open_until = time.time() + open_seconds
        self._circuit_breaker_opens += 1
        self._probe_mode = False
        logger.critical(
            f"[GoogleScheduler] Circuit Breaker OPENED for {open_seconds}s "
            f"(backoff step {self._backoff_step})"
        )

    def _record_outcome(self, success: bool) -> None:
        """Record an HTTP-level outcome and open circuit if threshold exceeded."""
        self._outcome_window.append(success)
        min_samples = getattr(config, "GOOGLE_CB_MIN_SAMPLES", 6)
        if len(self._outcome_window) < min_samples:
            return
        
        failures = sum(1 for o in self._outcome_window if not o)
        ratio = failures / len(self._outcome_window)
        if ratio >= self._cb_fail_threshold and not self._is_circuit_open() and not self._probe_mode:
            self._open_circuit()

    def _record_success(self) -> None:
        if self._probe_mode:
            self._probe_successes += 1
            if self._probe_successes >= 2:
                logger.info("[GoogleScheduler] PROBE succeeded (2/2). Closing circuit.")
                self._probe_mode = False
                self._backoff_step = 0
                self._circuit_open_until = 0.0
                self._outcome_window.clear()
        else:
            self._record_outcome(True)

    def _record_cb_failure(self) -> None:
        if self._probe_mode:
            logger.warning("[GoogleScheduler] PROBE failed. Re-opening circuit.")
            self._backoff_step += 1
            self._open_circuit()
        else:
            self._record_outcome(False)

    # ── Public API ────────────────────────────────────────────────────────────

    def schedule_search(self, query: str, max_results: int, page: int, provider) -> List[SearchResult]:
        if self._is_circuit_open():
            remaining = int(self._circuit_open_until - time.time())
            logger.warning(f"[GoogleScheduler] Circuit Breaker OPEN — skipping Google for {remaining}s.")
            raise ProviderUnavailable(
                "google_html", f"Google Circuit Breaker is OPEN. Remaining: {remaining}s"
            )

        proxy_manager = provider._client.proxy_manager

        healthy_count = 0
        with proxy_manager._lock:
            for p in proxy_manager._proxies:
                if p.dead or p.is_cooling_down("www.google.com"):
                    continue
                budget = getattr(config, "GOOGLE_REQUEST_BUDGET", 6)
                if p.has_google_budget(budget):
                    healthy_count += 1

        if healthy_count > 20:
            target_workers = 3
        elif healthy_count >= 10:
            target_workers = 2
        else:
            target_workers = 1
            
        # Dynamically resize the ThreadPoolExecutor
        if getattr(self._executor, "_max_workers", None) != target_workers:
            self._executor._max_workers = target_workers
            logger.info(f"[GoogleScheduler] Resized max_workers to {target_workers} (Healthy proxies: {healthy_count})")

        if healthy_count == 0:
            logger.warning("[GoogleScheduler] No healthy proxies with budget. Aborting Google search.")
            raise ProviderUnavailable("google_html", "No healthy Google proxies with budget available.")

        logger.info(f"[GoogleScheduler] Submitting query to executor: '{query}'")
        future = self._executor.submit(self._execute_search, query, max_results, page, provider, healthy_count)
        return future.result()

    def _execute_search(self, query: str, max_results: int, page: int, provider, healthy_count: int) -> List[SearchResult]:
        proxy_manager = provider._client.proxy_manager
        exclude_urls: set = set()
        session_id = f"google_html_{threading.get_ident()}"
        
        # Reduce Google retries to exactly 1 proxy retry (total 2 attempts)
        max_retries = 2

        attempts = 0
        zero_result_retries = 0
        last_error = None
        was_block = False

        while attempts < max_retries:
            from utils.deadline import Deadline
            if attempts > 0 and Deadline.is_exceeded():
                logger.warning("[GoogleScheduler] Global deadline exceeded. Aborting Google search retries.")
                break

            if self._is_circuit_open():
                logger.warning("[GoogleScheduler] Circuit breaker opened during retry loop.")
                break

            self._apply_delay(was_block=was_block, healthy_count=healthy_count)
            was_block = False

            proxy = proxy_manager.get_proxy(
                session_id=session_id,
                domain="www.google.com",
                exclude_urls=exclude_urls
            )
            if not proxy:
                logger.warning(
                    f"[GoogleScheduler] No more healthy proxies after {attempts} attempts."
                )
                break

            exclude_urls.add(proxy.raw_url)
            attempts += 1

            # Log tier and derived score for the selected proxy
            try:
                tier = proxy.get_google_tier()
                dscore = proxy.get_derived_score()
                logger.info(
                    f"[GoogleScheduler] [Attempt {attempts}/{max_retries}] "
                    f"Query: '{query}' via proxy {proxy.raw_url} "
                    f"(Tier {tier.value}, derived={dscore:.3f}, score={proxy.proxy_score:.1f})"
                )
            except Exception:
                logger.info(
                    f"[GoogleScheduler] [Attempt {attempts}/{max_retries}] "
                    f"Query: '{query}' via proxy {proxy.raw_url}"
                )

            # Smart session reset: clear cookies, connections, and User-Agents on block or proxy rotation
            if was_block or attempts > 1:
                try:
                    provider._client.session_manager.clear_session(session_id)
                    logger.info(f"[GoogleScheduler] Rotated session/User-Agent for thread session: {session_id}")
                except Exception:
                    pass

            proxy_manager.set_sticky_proxy(session_id, proxy)

            try:
                t_start = time.time()
                results, val_result = provider._execute_search_query(query, max_results, page, session_id=session_id)
                latency_s = time.time() - t_start
                print(f"[GoogleScheduler] Request validation status: {val_result.status} | proxy={proxy.raw_url} | latency={latency_s:.2f}s")

                if val_result.status == "VALID_RESULTS":
                    proxy.record_google_request()
                    proxy.record_success(domain="www.google.com", reason=val_result.status, latency_s=latency_s)
                    proxy_manager.mark_successful(proxy)
                    self._record_success()

                    from search.manager import get_search_manager
                    sm = get_search_manager()
                    sm.google_successes += 1

                    logger.info(f"[GoogleScheduler] SUCCESS on attempt {attempts} via {proxy.raw_url} ({val_result.status}, {latency_s:.2f}s)")
                    return results

                elif val_result.status == "VALID_ZERO_RESULTS":
                    expectation_score = get_query_expectation_score(query)
                    if expectation_score >= 0.5 and zero_result_retries < 2:
                        zero_result_retries += 1
                        logger.warning(
                            f"[GoogleScheduler] Zero results on attempt {attempts} via {proxy.raw_url}. "
                            f"Expectation is high ({expectation_score:.1f}). Verifying with another proxy (retry {zero_result_retries}/2)..."
                        )
                        # Downrate the proxy to rotate
                        proxy.record_google_request()
                        proxy.record_failure(domain="www.google.com", error=Exception("Zero results soft-block"), reason="RATE_LIMIT", latency_s=latency_s)
                        self._record_cb_failure()
                        was_block = True
                        continue
                    else:
                        proxy.record_google_request()
                        proxy.record_success(domain="www.google.com", reason=val_result.status, latency_s=latency_s)
                        proxy_manager.mark_successful(proxy)
                        self._record_success()

                        from search.manager import get_search_manager
                        sm = get_search_manager()
                        sm.google_successes += 1

                        logger.info(f"[GoogleScheduler] SUCCESS (Zero Results accepted) on attempt {attempts} via {proxy.raw_url} ({val_result.status}, {latency_s:.2f}s)")
                        return results

                elif val_result.status in _PARSER_FAIL_STATUSES:
                    proxy.record_google_request()
                    logger.warning(f"[GoogleScheduler] PARSER FAILURE ({val_result.status}) — NOT rotating proxy.")
                    raise ProviderParseError(provider.name, val_result.failure_reason or val_result.status)

                else:
                    proxy.record_google_request()
                    proxy.record_failure(domain="www.google.com", error=Exception(val_result.failure_reason or val_result.status), reason=val_result.status, latency_s=latency_s)
                    self._record_cb_failure()
                    was_block = True

                    from search.manager import get_search_manager
                    sm = get_search_manager()
                    sm.google_retries += 1
                    
                    if val_result.status == "RATE_LIMIT":
                        sm.google_429s += 1
                        sm.google_sorry_pages += 1
                    elif val_result.status == "CAPTCHA":
                        sm.google_captchas += 1
                    elif val_result.status == "ENABLE_JS":
                        sm.google_enable_js_queries += 1
                        sm.google_enablejs_pages += 1
                    elif val_result.status == "CONSENT_PAGE":
                        sm.google_consent_pages += 1
                        # Fail fast on consent page
                        last_error = ProviderUnavailable(provider.name, "CONSENT_PAGE")
                        break

                    last_error = ProviderUnavailable(provider.name, val_result.failure_reason or val_result.status)
                    
            except ProviderParseError:
                raise
            except Exception as e:
                latency_s = time.time() - t_start if 't_start' in dir() else 0.0
                print(f"[GoogleScheduler] Request validation status: NETWORK_FAILURE | proxy={proxy.raw_url}")
                proxy.record_google_request()
                proxy.record_failure(domain="www.google.com", error=e, reason="NETWORK_FAILURE", latency_s=latency_s)
                self._record_cb_failure()
                last_error = e
                was_block = True

        logger.error(f"[GoogleScheduler] All {attempts} retries failed for: '{query}'")
        raise ProviderUnavailable(
            "google_html",
            f"Google search failed after {attempts} proxy retries. Last error: {last_error}"
        )

    def _apply_delay(self, was_block: bool = False, healthy_count: int = 10) -> None:
        """Apply a pacing delay between proxy attempts. Reduced delay if previous attempt was a block or proxies are scarce."""
        if was_block:
            delay = random.uniform(0.5, 1.5)
        elif healthy_count <= 1:
            # Reduce delay dynamically when only 1 healthy proxy remains
            delay = random.uniform(1.0, 2.5)
        else:
            delay = random.uniform(
                getattr(config, "GOOGLE_DELAY_MIN", 2.0),
                getattr(config, "GOOGLE_DELAY_MAX", 6.0)
            )
        logger.info(f"[GoogleScheduler] Pacing delay: {delay:.2f}s")
        time.sleep(delay)

    def get_circuit_breaker_stats(self) -> dict:
        """Return circuit breaker state for diagnostics."""
        window = list(self._outcome_window)
        failures = sum(1 for o in window if not o)
        ratio = (failures / len(window)) if window else 0.0
        return {
            "circuit_open": self._is_circuit_open(),
            "circuit_open_until": self._circuit_open_until,
            "total_opens": self._circuit_breaker_opens,
            "window_size": len(window),
            "window_failures": failures,
            "failure_ratio": ratio,
            "probe_mode": self._probe_mode,
            "backoff_step": self._backoff_step
        }
