from contextvars import ContextVar
from typing import Optional

NO_REQUEST_ID = "-"

_request_id : ContextVar[Optional[str]] = ContextVar("request_id", default=None)

def set_request_id(request_id : str) -> None:
    _request_id.set(request_id)

def get_request_id() -> Optional[str]:
    return _request_id.get() or NO_REQUEST_ID