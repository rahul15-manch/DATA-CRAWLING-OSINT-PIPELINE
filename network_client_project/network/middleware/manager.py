import logging
from typing import List, Optional, Any, Union
from .base import Request, Response, BaseMiddleware

logger = logging.getLogger(__name__)

class MiddlewareManager:
    def __init__(self, middlewares: List[BaseMiddleware]):
        self.middlewares = middlewares
        logger.debug(f"MiddlewareManager initialized with {len(middlewares)} middlewares.")

    def process_request(self, request: Request, client: Any) -> Optional[Union[Request, Response]]:
        """Runs process_request hooks from first to last."""
        for mw in self.middlewares:
            res = mw.process_request(request, client)
            if isinstance(res, (Request, Response)):
                return res
        return None

    def process_response(self, request: Request, response: Response, client: Any) -> Union[Request, Response]:
        """Runs process_response hooks from last to first (reverse order)."""
        current_res = response
        for mw in reversed(self.middlewares):
            res = mw.process_response(request, current_res, client)
            if isinstance(res, Request):
                return res
            current_res = res
        return current_res

    def process_exception(self, request: Request, exception: Exception, client: Any) -> Optional[Union[Request, Response]]:
        """Runs process_exception hooks from last to first (reverse order)."""
        for mw in reversed(self.middlewares):
            res = mw.process_exception(request, exception, client)
            if isinstance(res, (Request, Response)):
                return res
        return None
