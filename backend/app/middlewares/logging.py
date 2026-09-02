import time
import logging
from typing import Optional
from urllib.parse import urlencode

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp
from starlette.requests import Request
from starlette.responses import Response

_SENSITIVE_QUERY = {
    "password", "token", "access_token", "refresh_token", "secret", "api_key",
}
_REDACTED = "[REDACTED]"

logger = logging.getLogger(__name__)

class LoggingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app : ASGIApp, slow_request_ms : int =1000):
        super().__init__(app)
        self.slow_request_ms = slow_request_ms

    async def dispatch(self, request: Request, call_next : RequestResponseEndpoint) -> Response:
        started = time.perf_counter()
        method = request.method
        path = request.url.path

        logger.info(
            "request_started",
            extra={
                "method": method,
                "path": path,
                "query": self._safe_query(request),
                "client_ip": request.client.host if request.client else None,
            }
        )

        status_code = 500
        size : Optional[str] = None

        try : 
            response = await call_next(request)
            status_code = response.status_code
            size = response.headers.get("content-length")
            return response

        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.info(
                "request_finished",
                extra={
                    "method": method,
                    "path": path,
                    "status": status_code,
                    "duration_ms": duration_ms,
                    "response_size": size,
                },
            )
            if duration_ms > self.slow_request_ms:
                logger.warning(
                    "slow_request",
                    extra={"method": method, "path": path, "duration_ms": duration_ms},
                )

@staticmethod
def _safe_query(request : Request) -> Optional[str]:
    
    if not request.url.query:
        return None
    
    pairs = [
        (key, _REDACTED if key.lower() in _SENSITIVE_QUERY else value)
        for key, value in request.query_params.multi_items()
    ]
    
    return urlencode(pairs)
       
        
