from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from functools import lru_cache
from pathlib import Path

class Settings(BaseSettings):
    model_config =  SettingsConfigDict(
        env_file = ".env",
        env_file_encoding = "utf-8",
        extra = "ignore"
    )

    app_env: str = "dev"
    secret_key: str

    # --- Auth (Phase 1) ---
    allowed_origins: list[str] = []
    ticket_ttl_seconds: int = 30

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

    class Config:
        env_file = Path(__file__).resolve().parent.parent.parent / ".env"

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_method(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip().rstrip("/") for item in value.split(",") if item.strip()]
        return value

    @property
    def is_dev(self) -> bool:
        return self.app_env == "dev"

@lru_cache
def get_settings() -> Settings:
    return Settings()