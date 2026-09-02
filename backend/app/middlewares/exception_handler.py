import logging
from typing import Any, Dict, List

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.context import get_request_id

logger = logging.getLogger("middleware.exceptions")

GENERIC_500_DETAIL = "Internal server error"


def _request_id(request : Request) -> str:
    return getattr(request.state, "request_id", None) or get_request_id()


def _safe_errors(exc : RequestValidationError) -> List[Dict[str, Any]]:
    return [
        {
            "field": ".".join(str(part) for part in err.get("loc", ())),
            "type": err.get("type"),
        }
        for err in exc.errors()
    ]


def register_exception_handlers(app : FastAPI) -> None:

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request : Request, exc : StarletteHTTPException) -> JSONResponse:
        logger.info(
            "http_exception",
            extra={
                "status": exc.status_code,
                "path": request.url.path,
                "detail": str(exc.detail),
            },
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "request_id": _request_id(request)},
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request : Request, exc : RequestValidationError) -> JSONResponse:
        errors = _safe_errors(exc)
        logger.warning(
            "validation_error",
            extra={"path": request.url.path, "errors": errors},
        )
        return JSONResponse(
            status_code=422,
            content={"detail": errors, "request_id": _request_id(request)},
        )

    @app.exception_handler(Exception)
    async def handle_unhandled(request : Request, exc : Exception) -> JSONResponse:
        logger.error(
            "unhandled_exception",
            exc_info=exc,
            extra={"path": request.url.path, "method": request.method},
        )
        return JSONResponse(
            status_code=500,
            content={"detail": GENERIC_500_DETAIL, "request_id": _request_id(request)},
        )