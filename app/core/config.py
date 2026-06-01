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
    public_base_url: str = Field(default="http://localhost:8000")
    default_book_id: str = Field(default="dip4e")

    api_key: str = Field(default="change-me")
    require_api_key: bool = Field(default=True)
    protect_assets: bool = Field(default=False)

    render_dpi: int = Field(default=180, ge=72, le=600)

    cors_allow_origins: list[str] = Field(default_factory=lambda: ["*"])

    @property
    def books_dir(self) -> Path:
        return self.data_dir / "books"

    def make_public_url(self, path: str) -> str:
        base = self.public_base_url.rstrip("/")
        path = path if path.startswith("/") else f"/{path}"
        return f"{base}{path}"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.books_dir.mkdir(parents=True, exist_ok=True)
    return settings
