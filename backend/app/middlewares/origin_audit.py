import logging

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)


class OriginAuditMiddleware(BaseHTTPMiddleware):
    """Names the origin CORSMiddleware is about to reject.

    A disallowed preflight gets answered with a bare 400 and no log line, so a
    wrong ALLOWED_ORIGINS surfaces only as an opaque CORS error in someone
    else's browser. Must sit outside CORSMiddleware to see preflights at all,
    since those are short-circuited and never reach the router.
    """

    def __init__(self, app: ASGIApp, allowed_origins: list[str]) -> None:
        super().__init__(app)
        self.allowed_origins = allowed_origins

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        origin = request.headers.get("origin")

        if origin and "*" not in self.allowed_origins and origin not in self.allowed_origins:
            logger.warning(
                "cors_origin_rejected",
                extra={
                    "origin": origin,
                    "allowed_origins": self.allowed_origins,
                    "path": request.url.path,
                },
            )

        return await call_next(request)
