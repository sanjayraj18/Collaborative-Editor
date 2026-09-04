import hashlib
import logging

import redis
from fastapi import HTTPException, Request, status

from app.config import get_settings
from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)


KEY_PREFIX = "rl:signin"


def _too_many(retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Too many sign-in attempts. Try again shortly.",
        headers={"Retry-After": str(retry_after)},
    )


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _ip_key(request: Request) -> str:
    return f"{KEY_PREFIX}:ip:{_client_ip(request)}"


def _email_key(email: str) -> str:
    digest = hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()
    return f"{KEY_PREFIX}:email:{digest[:32]}"


def _hit(key: str, window: int) -> tuple[int, int] | None:
    try:
        pipe = get_redis().pipeline()
        pipe.incr(key)
        pipe.expire(key, window, nx=True)
        pipe.ttl(key)
        count, _, ttl = pipe.execute()
        return int(count), int(ttl)

    except redis.RedisError as exc:
        logger.warning("ratelimit_unavailable key=%s error=%s", key, exc)
        return None


def enforce_login_rate_limit(request: Request, email: str) -> None:

    settings = get_settings()

    for key in (_ip_key(request), _email_key(email)):
        result = _hit(key, settings.login_rate_window_seconds)

        if result is None:
            if settings.rate_limit_fail_open:
                return
            # Redis is down, so there is no TTL to report. Fall back to the
            # configured window as the Retry-After hint.
            raise _too_many(settings.login_rate_window_seconds)

        count, ttl = result
        if count > settings.login_rate_limit:
            logger.warning("ratelimit_block key=%s count=%d", key, count)
            raise _too_many(max(ttl, 1))


def clear_login_rate_limit(email: str) -> None:
    try:
        get_redis().delete(_email_key(email))
    except redis.RedisError as exc:
        logger.warning("ratelimit_clear_failed error=%s", exc)
