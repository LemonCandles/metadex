"""Typed application settings loaded from environment variables."""

from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pydantic import Field, HttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Validate and centralize all settings shared by backend modules."""

    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    opendota_base_url: HttpUrl = HttpUrl("https://api.opendota.com/api")
    opendota_api_key: SecretStr | None = None
    data_dir: Path = Path("data")
    duckdb_path: Path = Path("data/metadex.duckdb")
    meta_window_days: int = Field(default=7, ge=1, le=365)
    min_sample_size: int = Field(default=100, ge=1)
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, values: list[str]) -> list[str]:
        for value in values:
            HttpUrl(value)
            origin = urlsplit(value)
            if (
                origin.scheme not in ("http", "https")
                or not origin.netloc
                or origin.username
                or origin.password
                or origin.path not in ("", "/")
                or origin.query
                or origin.fragment
            ):
                raise ValueError(
                    "CORS_ORIGINS must contain HTTP origins without credentials or paths"
                )
        return list(dict.fromkeys(str(HttpUrl(value)).rstrip("/") for value in values))

    @field_validator("opendota_api_key", mode="before")
    @classmethod
    def empty_api_key_is_absent(cls, value: Any) -> Any:
        """Treat an empty environment variable as an optional key."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("opendota_base_url")
    @classmethod
    def base_url_has_no_query_or_fragment(cls, value: HttpUrl) -> HttpUrl:
        """Keep credentials and request parameters out of the shared base URL."""
        if value.username or value.password or value.query or value.fragment:
            raise ValueError(
                "OPENDOTA_BASE_URL must not contain credentials, a query, or a fragment"
            )
        return value

    @field_validator("data_dir", "duckdb_path", mode="after")
    @classmethod
    def resolve_backend_path(cls, value: Path) -> Path:
        """Make relative paths independent from the shell's working directory."""
        if not value.is_absolute():
            value = BACKEND_ROOT / value
        return value.resolve()

    @field_validator("duckdb_path")
    @classmethod
    def duckdb_uses_expected_suffix(cls, value: Path) -> Path:
        """Catch accidental directory names or unrelated files early."""
        if value.suffix != ".duckdb":
            raise ValueError("DUCKDB_PATH must point to a .duckdb file")
        return value


@lru_cache
def get_settings() -> Settings:
    """Build settings once for the application process."""
    return Settings()
