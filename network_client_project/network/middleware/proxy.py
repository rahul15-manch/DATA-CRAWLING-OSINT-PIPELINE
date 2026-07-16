from typing import Optional, Union, Any
from urllib.parse import urlparse
from .base import BaseMiddleware, Request, Response
from ..exceptions import NetworkClientError

class ProxyMiddleware(BaseMiddleware):
    """
    Middleware that manages proxy assignment and routing for outgoing HTTP requests.

    Respects config.PROVIDER_CONNECTION_POLICY:
      proxy_only   → always select a proxy; raise if none available.
      direct_first → skip proxy (direct IP); the RetryMiddleware will
                     set require_proxy=True on retryable failures.
    """
    priority = 200

    def process_request(self, request: Request, client: Any) -> Optional[Union[Request, Response]]:
        session_id = request.meta.get("session_id")
        
        # If keep_proxy is set, reuse the sticky session proxy
        if request.meta.get("keep_proxy") and session_id:
            proxy = client.proxy_manager._sticky_sessions.get(session_id)
            if proxy:
                request.meta["_proxy_obj"] = proxy
                request.meta["proxies"] = proxy.formatted
                return None

        bypass_proxy = request.meta.get("bypass_proxy", False)
        require_proxy = request.meta.get("require_proxy", False)
        provider = request.meta.get("provider")

        domain = urlparse(request.url).netloc

        # ── Apply connection policy if provider is known ─────────────────
        if provider and not bypass_proxy and not require_proxy:
            import config
            policy = config.PROVIDER_CONNECTION_POLICY.get(provider, "direct_first")
            if policy == "proxy_only":
                require_proxy = True
                request.meta["require_proxy"] = True
            elif policy == "direct_first" and not request.meta.get("_policy_retry"):
                # First attempt: go direct (no proxy)
                bypass_proxy = True
                request.meta["bypass_proxy"] = True

        if bypass_proxy:
            request.meta["_proxy_obj"] = None
            request.meta["proxies"] = None
            # Clear sticky session link
            with client.proxy_manager._lock:
                client.proxy_manager._sticky_sessions.pop(session_id, None)
            return None

        # Fetch a proxy from the manager
        proxy = client.proxy_manager.get_proxy(session_id, domain=domain, provider=provider)
        
        if require_proxy and not proxy:
            raise NetworkClientError(f"No healthy proxies available for {domain}")

        # Attach proxy to request context
        request.meta["_proxy_obj"] = proxy
        request.meta["proxies"] = proxy.formatted if proxy else None
        return None
