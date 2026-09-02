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

    # --- Auth (Phase 1) ---
    # NoDecode suppresses pydantic-settings' JSON parsing of complex types,
    # which otherwise runs BEFORE our validator and chokes on a CSV string.
    allowed_origins: Annotated[list[str], NoDecode] = []
    ticket_ttl_seconds: int = 30

    # --- JWT / sessions ---
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 10
    refresh_token_expire_days: int = 30

    # --- Liveness (Phase 4) ---
    ping_interval_seconds: int = 20
    pong_timeout_seconds: int = 45

    # --- Backpressure (Phase 2) ---
    max_frame_bytes: int = 1024 * 1024
    send_queue_max_frames: int = 256
    send_queue_max_bytes: int = 8 * 1024 * 1024

    # --- Rooms (Phase 3) / resume (Phase 8) ---
    room_idle_ttl_seconds: int = 60
    resume_ring_size: int = 1024

    # --- Infra ---
    database_url: str = "postgresql://collab:collab@localhost:5432/collab"
    redis_url: str = "redis://localhost:6379/0"

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip().rstrip("/") for item in value.split(",") if item.strip()]
        return value

    @field_validator("secret_key", "jwt_secret_key")
    @classmethod
    def _reject_weak_secret(cls, value: str) -> str:
        # RFC 7518 3.2: an HMAC-SHA256 key must be at least as long as the
        # digest. A short key silently weakens every token we issue.
        if value and len(value.encode("utf-8")) < 32:
            raise ValueError("must be at least 32 bytes; generate with secrets.token_urlsafe(48)")
        return value

    @model_validator(mode="after")
    def _default_jwt_secret(self) -> "Settings":
        # Domain separation is nice-to-have; a working default is mandatory.
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
