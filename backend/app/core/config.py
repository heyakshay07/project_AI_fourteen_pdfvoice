from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    app_env: str = "development"
    secret_key: str = "change-me"
    access_token_expire_minutes: int = 60 * 24
    cors_origins: str = "http://localhost:5173"

    # Database
    database_url: str = "sqlite:///./pdfvoice.db"

    # Background tasks
    task_backend: str = "inline"  # "celery" | "inline"
    redis_url: str = "redis://localhost:6379/0"

    # Storage
    storage_backend: str = "local"  # "local" | "s3"
    storage_dir: str = "./storage"
    s3_bucket: str = ""
    s3_endpoint_url: str = ""
    s3_region: str = "us-east-1"
    s3_access_key: str = ""
    s3_secret_key: str = ""

    # Uploads
    max_upload_mb: int = 100
    max_pages: int = 5000

    # Extraction
    ocr_languages: str = "eng+hin+mar"
    ocr_dpi: int = 200
    ocr_min_chars: int = 25
    dehyphenate: bool = True

    # Chunking / audio
    chunk_max_chars: int = 600
    sentence_gap_seconds: float = 0.30
    heading_gap_seconds: float = 0.70
    audio_format: str = "mp3"  # "mp3" | "wav"
    default_tts_engine: str = "kokoro"
    default_voice: str = "af_heart"
    default_language: str = "en"

    @field_validator("task_backend")
    @classmethod
    def _check_backend(cls, v: str) -> str:
        if v not in {"celery", "inline"}:
            raise ValueError("TASK_BACKEND must be 'celery' or 'inline'")
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def storage_path(self) -> Path:
        return Path(self.storage_dir).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
