import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from app.config import get_settings
from app.middlewares.logging import LoggingMiddleware
from app.core.logging_config import setup_logging
from app.middlewares.exception_handler import register_exception_handlers
from app.middlewares.request_id import RequestIDMiddleware
from fastapi import FastAPI

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

@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}