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
        # 1. 404 Not Found: never retry
        if response.status_code == 404:
            return response

        # 2. Parser failure or layout page: NO retry
        if response.meta.get("is_parser_failure") or response.meta.get("is_unknown_layout"):
            return response

        # 3. 429 Too Many Requests
        if response.status_code == 429:
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
        if any(x in err_str for x in ["connection closed", "connection reset", "connection refused", "connect failed", "proxy connect aborted"]):
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

        # TLS / SSL Error: mark proxy capability as TLS_ERROR, retry once with different proxy
        if any(x in err_str for x in ["ssl", "tls", "handshake"]):
            proxy_obj = request.meta.get("_proxy_obj")
            if proxy_obj:
                provider = request.meta.get("provider", "default")
                domain_key = proxy_obj._normalize_provider_key(provider)
                proxy_obj.provider_capabilities[domain_key] = "TLS_ERROR"
                
                # Exclude the TLS failing proxy
                request.meta["exclude_urls"] = request.meta.get("exclude_urls", set()) | {proxy_obj.raw_url}
                
            session_id = request.meta.get("session_id")
            if session_id:
                with client.proxy_manager._lock:
                    client.proxy_manager._sticky_sessions.pop(session_id, None)
            return self._retry(request, exception=exception)

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
        
        if "query_start_time" not in request.meta:
            request.meta["query_start_time"] = time.time()
        elif time.time() - request.meta["query_start_time"] > 15.0:
            logger.warning(f"[Retry] Query time budget exceeded (15s) for {request.url}")
            return response if response else None

        retry_times = request.meta.get("retry_times", 0)
        
        max_retries = self.max_retries
        if "bing" in request.meta.get("provider", ""):
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
