import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.core.logging_config import setup_logging
from app.middlewares.cors import CORSMiddleware
from app.config import settings
from app.middlewares.exception_handler import register_exception_handlers
from app.middlewares.logging import LoggingMiddleware
from app.middlewares.request_id import RequestIDMiddleware
from app.rooms import permissions
from app.rooms.registry import registry
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

    registry.start_reaper()
    permissions.start()
    logger.info("startup env=%s origins=%s", settings.app_env, settings.allowed_origins)
    yield
    await permissions.stop()
    await registry.drain_all()
    logger.info("shutdown complete")


app = FastAPI(title="Collab", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,   # required — the refresh_token cookie won't be sent otherwise
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(LoggingMiddleware)
app.add_middleware(RequestIDMiddleware)


register_exception_handlers(app)


app.include_router(auth_router, prefix="/api")
app.include_router(doc_router, prefix="/api")
app.include_router(ws_router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
