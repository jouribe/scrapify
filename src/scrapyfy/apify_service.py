from __future__ import annotations

import json
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from apify_client import ApifyClient

from scrapyfy.config import CompanyTarget, Paths, Settings
from scrapyfy.logging_config import get_logger

logger = get_logger(__name__)


class ApifyService:
    def __init__(self, settings: Settings, paths: Paths) -> None:
        self.settings = settings
        self.paths = paths
        self.client = ApifyClient(settings.apify_api_token) if settings.apify_api_token else None

    def run_actor(self, actor_id: str, actor_input: dict[str, Any]) -> list[dict[str, Any]]:
        if self.client is None:
            raise ValueError("APIFY_API_TOKEN is required to run scraping commands")
        last_error: Exception | None = None
        logger.info("Starting actor run: actor_id=%s", actor_id)

        for attempt in range(1, 4):
            try:
                logger.info("Actor attempt %s/3: actor_id=%s", attempt, actor_id)
                run = self.client.actor(actor_id).call(run_input=actor_input)
                dataset_id = run["defaultDatasetId"]
                items = list(self.client.dataset(dataset_id).iterate_items())
                logger.info(
                    "Actor finished successfully: actor_id=%s dataset_id=%s items=%s",
                    actor_id,
                    dataset_id,
                    len(items),
                )
                return items
            except Exception as error:
                last_error = error
                logger.warning(
                    "Actor attempt failed: actor_id=%s attempt=%s error=%s",
                    actor_id,
                    attempt,
                    error,
                )
                if attempt < 3:
                    time.sleep(attempt * 2)

        logger.exception("Actor failed after retries: actor_id=%s", actor_id)
        raise RuntimeError(f"Actor execution failed for {actor_id}") from last_error

    def fetch_dataset_items(self, dataset_id: str) -> list[dict[str, Any]]:
        if self.client is None:
            raise ValueError("APIFY_API_TOKEN is required to fetch a dataset")
        items = list(self.client.dataset(dataset_id).iterate_items())
        logger.info("Dataset fetched: dataset_id=%s items=%s", dataset_id, len(items))
        return items

    def build_post_input(
        self,
        platform: str,
        company: CompanyTarget,
        limit_override: int | None = None,
    ) -> dict[str, Any]:
        template_file = self._post_template_file(platform)
        payload = self._load_json(template_file)

        if platform == "facebook":
            payload["startUrls"] = [{"url": self._facebook_url(company.handles.facebook)}]
            payload["resultsLimit"] = self.settings.max_posts_per_platform
        elif platform == "instagram":
            payload["username"] = [self._instagram_url(company.handles.instagram)]
            payload["resultsLimit"] = self.settings.max_posts_per_platform
        elif platform == "tiktok":
            payload["profiles"] = [self._tiktok_url(company.handles.tiktok)]
            payload["resultsPerPage"] = self.settings.max_posts_per_platform
        elif platform == "linkedin":
            payload["urls"] = [self._linkedin_url(company.handles.linkedin)]
            default_limit = self.settings.max_posts_per_platform
            limit = limit_override if limit_override is not None else default_limit
            payload["limitPerSource"] = limit
            try:
                payload["cookie"] = json.loads(self.settings.linkedin_cookie_json)
            except json.JSONDecodeError as error:
                raise ValueError("LINKEDIN_COOKIE_JSON contains invalid JSON") from error
        else:
            raise ValueError(f"Unsupported platform: {platform}")

        return payload

    def build_comments_input(self, platform: str, post_urls: list[str]) -> dict[str, Any]:
        template_file = self._comment_template_file(platform)
        payload = self._load_json(template_file)

        if platform == "facebook":
            payload["startUrls"] = [{"url": post_url} for post_url in post_urls]
            payload["resultsLimit"] = self.settings.max_comments_per_post
        elif platform == "instagram":
            payload["directUrls"] = post_urls
            payload["resultsLimit"] = self.settings.max_comments_per_post
        elif platform == "tiktok":
            payload["postURLs"] = post_urls
            payload["commentsPerPost"] = self.settings.max_comments_per_post
        else:
            raise ValueError(f"Unsupported comments platform: {platform}")

        return payload

    def _post_template_file(self, platform: str) -> Path:
        mapping = {
            "facebook": self.paths.inputs_dir / "facebook.json",
            "instagram": self.paths.inputs_dir / "instaqagram.json",
            "tiktok": self.paths.inputs_dir / "tiktok.json",
            "linkedin": self.paths.inputs_dir / "linkedin.json",
        }
        try:
            return mapping[platform]
        except KeyError as error:
            raise ValueError(f"Unsupported platform: {platform}") from error

    def _comment_template_file(self, platform: str) -> Path:
        mapping = {
            "facebook": self.paths.inputs_dir / "facebook_comments.json",
            "instagram": self.paths.inputs_dir / "instagram_comments.json",
            "tiktok": self.paths.inputs_dir / "tiktok_comments.json",
        }
        try:
            return mapping[platform]
        except KeyError as error:
            raise ValueError(f"Unsupported platform: {platform}") from error

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return deepcopy(payload)

    @staticmethod
    def _is_url(value: str) -> bool:
        return value.startswith("http://") or value.startswith("https://")

    def _facebook_url(self, value: str) -> str:
        if self._is_url(value):
            return value
        return f"https://www.facebook.com/{value.lstrip('/')}"

    def _instagram_url(self, value: str) -> str:
        if self._is_url(value):
            return value
        return f"https://www.instagram.com/{value.lstrip('@')}"

    def _tiktok_url(self, value: str) -> str:
        if self._is_url(value):
            return value
        username = value.lstrip("@")
        return f"https://www.tiktok.com/@{username}"

    def _linkedin_url(self, value: str) -> str:
        if self._is_url(value):
            return value
        return f"https://www.linkedin.com/company/{value.lstrip('/')}"
