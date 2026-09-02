import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from app.config import get_settings
from fastapi import FastAPI

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

@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}