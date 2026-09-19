import logging
from typing import Optional, Union, Any
from .base import BaseMiddleware, Request, Response

logger = logging.getLogger(__name__)

class CookieMiddleware(BaseMiddleware):
    """
    Middleware that tracks and logs cookie reuse across requests for persistent sessions.
    Strictly HTTP-level.
    """
    priority = 400
    def process_request(self, request: Request, client: Any) -> Optional[Union[Request, Response]]:
        session_id = request.meta.get("session_id")
        if session_id:
            session = client.session_manager.get_or_create_session(session_id)
            if session.cookies:
                logger.debug(f"[Cookie] Reusing {len(session.cookies)} cookies for session '{session_id}'")
        return None
