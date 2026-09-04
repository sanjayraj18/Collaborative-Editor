import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.core.logging_config import setup_logging
from app.middlewares.exception_handler import register_exception_handlers
from app.middlewares.logging import LoggingMiddleware
from app.middlewares.request_id import RequestIDMiddleware
from app.routes.auth_routes import router as auth_router
from app.routes.doc_routes import router as doc_router
from app.ws.endpoint import router as ws_router

setup_logging("DEBUG")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logger.info(
        "startup env=%s origins=%s",
        settings.app_env,
        settings.allowed_origins,
    )
    # Phase 7: open the Postgres pool here.
    yield
    # Phase 3: drain rooms here on shutdown.
    logger.info("shutdown complete")


app = FastAPI(title="Collab", version="0.1.0", lifespan=lifespan)
app.add_middleware(LoggingMiddleware)
app.add_middleware(RequestIDMiddleware)


register_exception_handlers(app)


app.include_router(auth_router, prefix="/api")
app.include_router(doc_router, prefix="/api")
app.include_router(ws_router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
