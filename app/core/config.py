from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env."""

    model_config = SettingsConfigDict(
        env_prefix="TEACHING_GPT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: Path = Field(default=Path("./data"))
    default_book_id: str = Field(default="dip4e")

    api_key: str = Field(default="change-me")
    require_api_key: bool = Field(default=True)

    cors_allow_origins: list[str] = Field(default_factory=lambda: ["*"])

    @property
    def books_dir(self) -> Path:
        return self.data_dir / "books"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.books_dir.mkdir(parents=True, exist_ok=True)
    return settings
