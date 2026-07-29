from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TEACHING_GPT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    locator_index_path: Path = Field(default=Path("./catalog/dip4e/compiled_locator_index.json"))
    api_key: str = Field(default="change-me")
    require_api_key: bool = Field(default=True)
    cors_allow_origins: list[str] = Field(default_factory=lambda: ["*"])


@lru_cache
def get_settings() -> Settings:
    return Settings()
