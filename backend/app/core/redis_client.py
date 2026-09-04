import logging
from functools import lru_cache

import redis

from app.config import get_settings

logger = logging.getLogger(__name__)

SOCKET_TIMEOUT_SECONDS = 0.25
CONNECT_TIMEOUT_SECONDS = 0.25


@lru_cache
def get_redis() -> redis.Redis:
    settings = get_settings()

    return redis.Redis.from_url(
        settings.redis_url,
        decode_response=False,
        socket_timeout=SOCKET_TIMEOUT_SECONDS,
        socket_connect_timeout=CONNECT_TIMEOUT_SECONDS,
        health_check_interval=30,
    )


def ping() -> bool:
    try:
        return bool(get_redis().ping())
    except redis.RedisError as exc:
        logger.warning("redis_unreachable error=%s", exc)
        return False
