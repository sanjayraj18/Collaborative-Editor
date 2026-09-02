import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp
from starlette.requests import Request
from starlette.responses import Response

from typing import Optional
from core.context import set_request_id

REQUEST_ID_HEADER = "X-Request-ID"

_MAX_LENGTH = 64
_ALLOWED_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
)


class RequestIDMiddleware(BaseHTTPMiddleware):

    def __init__(self, app : ASGIApp, header_name : str=REQUEST_ID_HEADER):
        super().__init__(app)
        self.header_name = header_name

    async def dispatch(self, request : Request, call_next : RequestResponseEndpoint) -> Response:
        incoming = self._clean(request.headers.get(self.header_name))

        request_id = incoming or str(uuid.uuid4())
        set_request_id(request_id)
        request.state.request_id = request_id

        response = await call_next(request)

        response.headers[self.header_name] = request_id
        return response

    @staticmethod
    def _clean(value : Optional[str]) -> Optional[str]:
        if not value:
            return None

        value = value.strip()
        if not value or len(value) > _MAX_LENGTH:
            return None
        if not set(value) <= _ALLOWED_CHARS:
            return None

        return value
