from __future__ import annotations

from functools import cached_property
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _split_csv(value: str | list[str]) -> list[str]:
    if isinstance(value, list):
        return value
    return [part.strip() for part in value.split(",") if part.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "production"
    log_level: str = "INFO"
    data_dir: Path = Path("data")
    database_url: str | None = None
    postal_code: str = "14221"
    search_radius_miles: float = 35.0
    lookahead_days: int = 15
    min_picture_count: int = 5
    allowed_sale_types: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["EstateSales", "MovingSales"]
    )
    estatesales_base_url: str = "https://www.estatesales.net"
    http_timeout_seconds: float = 30.0
    http_max_retries: int = 3
    http_request_delay_seconds: float = 0.35
    http_user_agent: str = (
        "Mozilla/5.0 (compatible; EstateSaleFinder/0.1; "
        "+https://github.com/tohutson/estate-sale-finder)"
    )
    sale_detail_batch_size: int = 40
    max_image_bytes: int = 15_000_000
    max_image_pixels: int = 24_000_000
    max_download_concurrency: int = 4
    keep_original_images: bool = False
    analysis_provider: Literal["mock", "openai"] = "mock"
    vision_model: str = "gpt-4.1-mini"
    vision_api_key: str | None = None
    vision_batch_size: int = 4
    vision_max_batch_attempts: int = 2
    vision_max_single_image_attempts: int = 2
    vision_retry_backoff_seconds: float = 1.0
    vision_max_images_per_run: int | None = None
    openai_save_responses: bool = False
    openai_response_log_dir: Path | None = None
    analysis_version: str = "golf-camera-v2"
    prompt_version: str = "targets-v2"
    local_prefilter_enabled: bool = False
    local_prefilter_model: str = "ViT-B-32/laion2b_s34b_b79k"
    local_prefilter_threshold: float = 0.20
    email_enabled: bool = False
    email_send_on_no_matches: bool = False
    email_send_on_failure: bool = False
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    email_from: str | None = None
    email_to: Annotated[list[str], NoDecode] = Field(default_factory=list)

    @field_validator("allowed_sale_types", "email_to", mode="before")
    @classmethod
    def parse_csv(cls, value: str | list[str]) -> list[str]:
        return _split_csv(value)

    @field_validator("data_dir", mode="after")
    @classmethod
    def expand_data_dir(cls, value: Path) -> Path:
        return value.expanduser()

    @model_validator(mode="after")
    def validate_feature_settings(self) -> Settings:
        if self.analysis_provider == "openai" and not self.vision_api_key:
            raise ValueError("VISION_API_KEY is required when ANALYSIS_PROVIDER=openai")
        retry_limits = {
            "VISION_BATCH_SIZE": self.vision_batch_size,
            "VISION_MAX_BATCH_ATTEMPTS": self.vision_max_batch_attempts,
            "VISION_MAX_SINGLE_IMAGE_ATTEMPTS": self.vision_max_single_image_attempts,
        }
        invalid_retry_limits = [
            name for name, value in retry_limits.items() if value < 1 or value > 25
        ]
        if invalid_retry_limits:
            raise ValueError(
                "Vision retry settings must be between 1 and 25: " + ", ".join(invalid_retry_limits)
            )
        if self.vision_retry_backoff_seconds < 0 or self.vision_retry_backoff_seconds > 300:
            raise ValueError("VISION_RETRY_BACKOFF_SECONDS must be between 0 and 300")
        if self.email_enabled:
            missing = [
                name
                for name, value in {
                    "SMTP_HOST": self.smtp_host,
                    "EMAIL_FROM": self.email_from,
                    "EMAIL_TO": self.email_to,
                }.items()
                if not value
            ]
            if missing:
                raise ValueError(f"Missing email settings: {', '.join(missing)}")
        return self

    @cached_property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.data_dir / 'estate-sale-finder.db'}"

    @property
    def images_dir(self) -> Path:
        return self.data_dir / "images"

    @property
    def thumbnails_dir(self) -> Path:
        return self.data_dir / "thumbnails"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def locks_dir(self) -> Path:
        return self.data_dir / "locks"

    def ensure_directories(self) -> None:
        for path in [
            self.data_dir,
            self.images_dir,
            self.thumbnails_dir,
            self.logs_dir,
            self.locks_dir,
        ]:
            path.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    return Settings()
