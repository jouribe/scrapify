from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    apify_api_token: str = Field(default="", alias="APIFY_API_TOKEN")
    database_url: str = Field(alias="DATABASE_URL")
    linkedin_cookie_json: str = Field(default="[]", alias="LINKEDIN_COOKIE_JSON")
    max_posts_per_platform: int = Field(default=200, alias="MAX_POSTS_PER_PLATFORM")
    max_comments_per_post: int = Field(default=200, alias="MAX_COMMENTS_PER_POST")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_file: str = Field(default="scrapyfy.log", alias="LOG_FILE")
    sentiment_model_id: str = Field(
        default="cardiffnlp/twitter-xlm-roberta-base-sentiment",
        alias="SENTIMENT_MODEL_ID",
    )
    sentiment_batch_size: int = Field(default=32, alias="SENTIMENT_BATCH_SIZE")
    sentiment_device: str = Field(default="cpu", alias="SENTIMENT_DEVICE")
    digitalocean_spaces_key: str = Field(default="", alias="DIGITALOCEAN_SPACES_KEY")
    digitalocean_spaces_secret: str = Field(default="", alias="DIGITALOCEAN_SPACES_SECRET")
    digitalocean_spaces_name: str = Field(default="", alias="DIGITALOCEAN_SPACES_NAME")
    digitalocean_spaces_region: str = Field(default="nyc3", alias="DIGITALOCEAN_SPACES_REGION")
    digitalocean_spaces_endpoint: str = Field(default="", alias="DIGITALOCEAN_SPACES_ENDPOINT")

    model_config = SettingsConfigDict(
        env_file=[Path.cwd() / ".env.local", Path.cwd() / ".env"],
        env_file_encoding="utf-8",
        extra="ignore",
    )


class CompanyHandles(BaseModel):
    facebook: str | None = None
    instagram: str | None = None
    tiktok: str | None = None
    linkedin: str | None = None
    youtube: str | None = None


class CompanyTarget(BaseModel):
    name: str
    slug: str
    handles: CompanyHandles


class TargetConfig(BaseModel):
    companies: list[CompanyTarget]


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def config_dir(self) -> Path:
        return self.root / "config"

    @property
    def inputs_dir(self) -> Path:
        return self.root / "inputs"

    @property
    def targets_file(self) -> Path:
        return self.root / "config" / "targets.yaml"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"


def load_targets(paths: Paths) -> TargetConfig:
    with paths.targets_file.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    return TargetConfig.model_validate(payload)
