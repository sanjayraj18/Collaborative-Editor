import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.core.logging_config import setup_logging
from app.database import schemas  # noqa: F401 -- registers models on Base
from app.database.database import Base, engine
from app.middlewares.exception_handler import register_exception_handlers
from app.middlewares.logging import LoggingMiddleware
from app.middlewares.request_id import RequestIDMiddleware
from app.routes.auth_routes import router as auth_router

setup_logging("DEBUG")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    Base.metadata.create_all(bind=engine)
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

# add_middleware is LIFO: the last added runs first, so RequestIDMiddleware
# sets the request id before LoggingMiddleware reads it.
app.add_middleware(LoggingMiddleware)
app.add_middleware(RequestIDMiddleware)

register_exception_handlers(app)
app.include_router(auth_router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
