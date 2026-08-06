from typing import Optional, Union, Any
from .base import BaseMiddleware, Request, Response

class HeaderMiddleware(BaseMiddleware):
    """
    Middleware that manages HTTP headers and rotates Chrome browser User-Agents.
    Strictly HTTP-level.
    """
    priority = 100
    def process_request(self, request: Request, client: Any) -> Optional[Union[Request, Response]]:
        session_id = request.meta.get("session_id")
        session = client.session_manager.get_or_create_session(session_id)

        # Retrieve or generate User-Agent for this session
        ua = getattr(session, "_custom_ua", None)
        if not ua:
            ua = client.ua_manager.get_chrome_desktop()
            session._custom_ua = ua

        # Generate fresh browser-like camouflage headers
        is_xhr = request.meta.get("is_xhr", False)
        headers = client.header_manager.generate_browser_headers(
            target_url=request.url,
            user_agent=ua,
            is_xhr=is_xhr
        )

        # Merge user-supplied headers on top
        if request.headers:
            headers.update(request.headers)

        # Remove Accept-Encoding so curl_cffi handles gzip/brotli automatically,
        # UNLESS the caller explicitly set it (e.g. to avoid brotli decompression issues)
        user_set_encoding = request.headers and "Accept-Encoding" in request.headers
        if not user_set_encoding:
            headers.pop("Accept-Encoding", None)

        request.headers = headers
        request.meta["user_agent"] = ua
        return None
