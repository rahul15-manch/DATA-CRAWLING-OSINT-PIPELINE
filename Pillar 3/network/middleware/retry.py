import time
import logging
import random
from typing import Optional, Union, Any
from .base import BaseMiddleware, Request, Response
from ..config import config
from ..exceptions import ErrorDetector, NetworkClientError

logger = logging.getLogger(__name__)

class RetryMiddleware(BaseMiddleware):
    """
    Middleware that handles request retries on WAF blocks, rate limits, or network failures.
    Strictly HTTP-level.
    """
    priority = 500
    def __init__(self, max_retries: int = None):
        super().__init__()
        self.max_retries = max_retries if max_retries is not None else config.MAX_RETRIES

    def process_response(self, request: Request, response: Response, client: Any) -> Union[Request, Response]:
        # Check if directory domain
        from urllib.parse import urlparse
        domain = urlparse(request.url).netloc.lower()
        is_directory = any(p in domain for p in ("clutch.co", "goodfirms.co", "crunchbase.com", "linkedin.com", "f6s.com"))
        
        if is_directory:
            waf_error = ErrorDetector.detect_waf_or_captcha(response)
            if response.status_code in (403, 429) or waf_error:
                logger.warning(f"[Retry] Rate limit or WAF block detected on directory {domain} (HTTP {response.status_code}). Bypassing immediate retry to bubble up to circuit breaker.")
                session_id = request.meta.get("session_id")
                if session_id:
                    with client.proxy_manager._lock:
                        client.proxy_manager._sticky_sessions.pop(session_id, None)
                proxy_obj = request.meta.get("_proxy_obj")
                if proxy_obj:
                    request.meta["exclude_urls"] = request.meta.get("exclude_urls", set()) | {proxy_obj.raw_url}
                return response  # Bubble up immediately!

        # 1. 404 Not Found: never retry
        if response.status_code == 404:
            return response

        # 2. Parser failure or layout page: NO retry
        if response.meta.get("is_parser_failure") or response.meta.get("is_unknown_layout"):
            return response

        # Check if search provider request
        is_search = request.meta.get("request_type") == "search" or request.meta.get("provider") in ("google_html", "brave", "bing", "duckduckgo", "brightdata")

        if is_search:
            waf_error = ErrorDetector.detect_waf_or_captcha(response)
            if response.status_code in (403, 429) or waf_error:
                logger.warning(f"[Retry] Search provider {request.meta.get('provider')} hit block/CAPTCHA/429 (HTTP {response.status_code}). Bubbling up immediately for fail-fast.")
                return response

        # 3. 429 Too Many Requests
        if response.status_code == 429:
            from urllib.parse import urlparse
            domain = urlparse(request.url).netloc.lower()
            is_directory = any(p in domain for p in ("clutch.co", "goodfirms.co", "crunchbase.com", "linkedin.com", "f6s.com"))
            
            if is_directory:
                session_id = request.meta.get("session_id")
                if session_id:
                    with client.proxy_manager._lock:
                        client.proxy_manager._sticky_sessions.pop(session_id, None)
                proxy_obj = request.meta.get("_proxy_obj")
                if proxy_obj:
                    request.meta["exclude_urls"] = request.meta.get("exclude_urls", set()) | {proxy_obj.raw_url}
                request.meta["retry_delay"] = 5.0
                logger.warning(f"[Retry] 429 rate limit hit on directory {domain}. Rotating proxy.")
                return self._retry(request, response, reason="429 Rate Limit (Rotate Proxy)", status_code=429, keep_proxy=False)
            else:
                # Increase delay, keep session/cookies, and reuse current proxy
                request.meta["keep_proxy"] = True
                request.meta["retry_delay"] = 15.0
                return self._retry(request, response, reason="429 Rate Limit (Same Proxy)", status_code=429, keep_proxy=True)

        # 4. CAPTCHA / 403 WAF blocks
        waf_error = ErrorDetector.detect_waf_or_captcha(response)
        if waf_error or response.status_code == 403:
            session_id = request.meta.get("session_id")
            if session_id:
                with client.proxy_manager._lock:
                    client.proxy_manager._sticky_sessions.pop(session_id, None)
            
            # Exclude current proxy if present
            proxy_obj = request.meta.get("_proxy_obj")
            if proxy_obj:
                request.meta["exclude_urls"] = request.meta.get("exclude_urls", set()) | {proxy_obj.raw_url}
                
            return self._retry(request, response, exception=waf_error or Exception("WAF CAPTCHA/403 block"), status_code=response.status_code)

        # 5. 500 / 503 errors (retry up to 2 times, rotating proxy)
        if response.status_code in (500, 503):
            retry_times = request.meta.get("retry_times", 0)
            if retry_times < 2:
                session_id = request.meta.get("session_id")
                if session_id:
                    with client.proxy_manager._lock:
                        client.proxy_manager._sticky_sessions.pop(session_id, None)
                proxy_obj = request.meta.get("_proxy_obj")
                if proxy_obj:
                    request.meta["exclude_urls"] = request.meta.get("exclude_urls", set()) | {proxy_obj.raw_url}
                return self._retry(request, response, reason=f"HTTP Status {response.status_code}", status_code=response.status_code)
            return response

        return response

    def process_exception(self, request: Request, exception: Exception, client: Any) -> Optional[Response]:
        err_str = str(exception).lower()
        
        # Connection reset / dead connection: retry once, different proxy
        if any(x in err_str for x in ["connection closed", "connection reset", "connection refused", "connect failed", "proxy connect aborted", "network error"]):
            retry_times = request.meta.get("retry_times", 0)
            if retry_times < 1:
                session_id = request.meta.get("session_id")
                if session_id:
                    with client.proxy_manager._lock:
                        client.proxy_manager._sticky_sessions.pop(session_id, None)
                proxy_obj = request.meta.get("_proxy_obj")
                if proxy_obj:
                    request.meta["exclude_urls"] = request.meta.get("exclude_urls", set()) | {proxy_obj.raw_url}
                return self._retry(request, exception=exception)
            return None

        # TLS / SSL Error: mark proxy capability as TLS_ERROR, do NOT retry (permanent TLS failure)
        if any(x in err_str for x in ["ssl", "tls", "handshake"]):
            proxy_obj = request.meta.get("_proxy_obj")
            if proxy_obj:
                provider = request.meta.get("provider", "default")
                domain_key = proxy_obj._normalize_provider_key(provider)
                proxy_obj.provider_capabilities[domain_key] = "TLS_ERROR"
                request.meta["exclude_urls"] = request.meta.get("exclude_urls", set()) | {proxy_obj.raw_url}
                
            session_id = request.meta.get("session_id")
            if session_id:
                with client.proxy_manager._lock:
                    client.proxy_manager._sticky_sessions.pop(session_id, None)
            logger.warning(f"[Retry] Permanent TLS failure detected for {request.url}. Bubbling up immediately.")
            return None

        # Timeout: retry with different proxy
        if "timeout" in err_str or "timed out" in err_str or "curl: (28)" in err_str:
            session_id = request.meta.get("session_id")
            if session_id:
                with client.proxy_manager._lock:
                    client.proxy_manager._sticky_sessions.pop(session_id, None)
            proxy_obj = request.meta.get("_proxy_obj")
            if proxy_obj:
                request.meta["exclude_urls"] = request.meta.get("exclude_urls", set()) | {proxy_obj.raw_url}
            res = self._retry(request, exception=exception, fast_retry=True)
            if isinstance(res, Request):
                return res

        return None

    def _retry(
        self, 
        request: Request, 
        response: Optional[Response] = None, 
        exception: Optional[Exception] = None, 
        reason: Optional[str] = None,
        status_code: Optional[int] = None,
        fast_retry: bool = False,
        keep_proxy: bool = False
    ) -> Union[Request, Response]:
        
        # Track retry reason for Issue 7 diagnostics log
        retry_reasons = request.meta.get("retry_reasons", [])
        if reason:
            retry_reasons.append(reason)
        elif exception:
            retry_reasons.append(exception.__class__.__name__)
        request.meta["retry_reasons"] = retry_reasons

        # Check Global Timeout / Cap
        from utils.deadline import Deadline
        if Deadline.is_exceeded():
            logger.warning(f"[Retry] Global deadline exceeded ({Deadline.remaining():.1f}s remaining). Aborting retry loop for {request.url}")
            return response if response else None

        if "query_start_time" not in request.meta:
            request.meta["query_start_time"] = time.time()
        else:
            query_timeout = getattr(config, "QUERY_TIMEOUT", 15.0)
            if time.time() - request.meta["query_start_time"] > query_timeout:
                logger.warning(f"[Retry] Query time budget exceeded ({query_timeout}s) for {request.url}")
                return response if response else None

        retry_times = request.meta.get("retry_times", 0)
        
        max_retries = self.max_retries
        pname = request.meta.get("provider", "")
        if "google" in pname:
            max_retries = 1
        elif "brave" in pname:
            max_retries = 1
        elif "bing" in pname:
            max_retries = 1
        elif status_code in (500, 503):
            max_retries = min(2, self.max_retries)
            
        if retry_times < max_retries:
            retry_times += 1
            request.meta["retry_times"] = retry_times

            if not keep_proxy:
                if request.meta.get("bypass_proxy"):
                    request.meta["bypass_proxy"] = False
                    request.meta["_policy_retry"] = True
                    request.meta["require_proxy"] = False  
                    request.meta["_attempted_direct"] = True
                else:
                    if not request.meta.get("_attempted_direct") and retry_times == max_retries:
                        request.meta["bypass_proxy"] = True
                        request.meta["_attempted_direct"] = True
                        logger.info(f"Falling back to direct connection for final retry on {request.url}")
            else:
                request.meta["keep_proxy"] = True

            # Retry delay selection
            if fast_retry:
                backoff = 0.1
            elif "retry_delay" in request.meta:
                backoff = request.meta["retry_delay"]
            else:
                backoff = (2 ** retry_times) + random.uniform(0.5, 1.5)
            
            err_msg = ""
            if exception:
                err_msg = f"due to: {exception.__class__.__name__} ({exception})"
            elif reason:
                err_msg = f"due to: {reason}"
                
            logger.warning(
                f"[Retry] Retrying query {request.url} (attempt {retry_times}/{max_retries}) "
                f"after {backoff:.2f}s delay {err_msg}."
            )
            
            time.sleep(backoff)
            return request

        if response:
            return response
        return None
