from functools import lru_cache
from typing import Annotated

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "dev"
    secret_key: str

    allowed_origins: Annotated[list[str], NoDecode] = []
    ticket_ttl_seconds: int = 30

    login_rate_limit: int = 10
    login_rate_window_seconds: int = 300
    rate_limit_fail_open: bool = True
    refresh_reuse_grace_seconds: int = 10

    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 10
    refresh_token_expire_days: int = 30

    ping_interval_seconds: int = 20
    pong_timeout_seconds: int = 45

    max_frame_bytes: int = 1024 * 1024
    send_queue_max_frames: int = 256
    send_queue_max_bytes: int = 8 * 1024 * 1024
    hello_timeout_seconds: float = 5.0
    slow_consumer_grace_seconds: float = 5.0

    room_inbox_max_frames: int = 1024
    room_idle_ttl_seconds: int = 60

    reaper_interval_seconds: int = 10
    permission_check_seconds: int = 30

    update_coalesce_ms: int = 20
    awareness_coalesce_ms: int = 100

    resume_ring_size: int = 1024

    database_url: str
    redis_url: str

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip().rstrip("/") for item in value.split(",") if item.strip()]
        return value

    @field_validator("secret_key", "jwt_secret_key")
    @classmethod
    def _reject_weak_secret(cls, value: str) -> str:
        if value and len(value.encode("utf-8")) < 32:
            raise ValueError("must be at least 32 bytes; generate with secrets.token_urlsafe(48)")
        return value

    @model_validator(mode="after")
    def _default_jwt_secret(self) -> "Settings":
        if not self.jwt_secret_key:
            self.jwt_secret_key = self.secret_key
        return self

    @property
    def is_dev(self) -> bool:
        return self.app_env == "dev"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
