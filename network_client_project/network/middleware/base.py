import uuid
import time
from typing import Optional, Any, Union

class Request:
    def __init__(
        self, 
        url: str, 
        method: str = "GET", 
        query: Optional[str] = None,
        provider: Optional[str] = None,
        priority: int = 0,
        retries: int = 0,
        headers: Optional[dict] = None,
        cookies: Optional[dict] = None, 
        proxy: Optional[str] = None,
        callback: Optional[Any] = None,
        meta: Optional[dict] = None,
        depth: int = 0,
        params: Optional[dict] = None, 
        data: Any = None, 
        json: Any = None, 
        timeout: Optional[float] = None, 
        verify: Optional[bool] = None
    ):
        self.id = uuid.uuid4().hex
        self.url = url
        self.method = method
        self.query = query
        self.provider = provider
        self.priority = priority
        self.retries = retries
        self.headers = headers or {}
        self.cookies = cookies or {}
        self.proxy = proxy
        self.callback = callback
        self.meta = meta or {}
        self.depth = depth
        self.timestamp = time.time()
        
        # Backward compatibility/HTTP parameters
        self.params = params or {}
        self.data = data
        self.json = json
        self.timeout = timeout
        self.verify = verify

class Response:
    def __init__(
        self, 
        request: Request, 
        status_code: int, 
        html: str, 
        latency_ms: float = 0.0,
        headers: Optional[dict] = None, 
        proxy: Optional[str] = None,
        parser: Optional[Any] = None,
        meta: Optional[dict] = None,
        content: Optional[bytes] = None
    ):
        self.request = request
        self.status_code = status_code
        self.html = html
        self.latency_ms = latency_ms
        self.headers = headers or {}
        self.proxy = proxy
        self.parser = parser
        self.meta = meta or (request.meta.copy() if request else {})
        self._content = content or html.encode('utf-8')

    @property
    def url(self) -> str:
        return self.request.url if self.request else ""

    @property
    def text(self) -> str:
        return self.html

    @property
    def content(self) -> bytes:
        return self._content

class BaseMiddleware:
    def process_request(self, request: Request, client: Any) -> Optional[Union[Request, Response]]:
        """
        Called for each request before it goes to the HTTP client.
        Must return:
        - None: continue processing this request.
        - Request object: stop running downstream process_request hooks, and start over with the new request.
        - Response object: stop running process_request hooks, and immediately run response middleware hooks.
        """
        return None

    def process_response(self, request: Request, response: Response, client: Any) -> Union[Request, Response]:
        """
        Called for each response received from the HTTP client or process_request.
        Must return:
        - Response object: continue processing this response.
        - Request object: discard the response and start a new request sequence.
        """
        return response

    def process_exception(self, request: Request, exception: Exception, client: Any) -> Optional[Response]:
        """
        Called when a middleware or the HTTP client raises an exception.
        Must return:
        - None: let the exception propagate.
        - Response object: handle the exception by converting it to a response.
        """
        return None
