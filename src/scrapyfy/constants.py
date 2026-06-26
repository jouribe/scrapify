from __future__ import annotations

from typing import Final

POST_ACTORS: Final[dict[str, str]] = {
    "facebook": "apify/facebook-posts-scraper",
    "instagram": "apify/instagram-post-scraper",
    "tiktok": "clockworks/tiktok-scraper",
    "linkedin": "curious_coder/linkedin-post-search-scraper",
}

COMMENT_ACTORS: Final[dict[str, str]] = {
    "facebook": "apify/facebook-comments-scraper",
    "instagram": "apify/instagram-comment-scraper",
    "tiktok": "clockworks/tiktok-comments-scraper",
}

COMMENT_PLATFORMS: Final[set[str]] = {"facebook", "instagram", "tiktok"}
COMMENT_IMPORT_PLATFORMS: Final[tuple[str, ...]] = (
    "facebook",
    "instagram",
    "tiktok",
    "youtube",
)
PLATFORMS: Final[tuple[str, ...]] = ("facebook", "instagram", "tiktok", "linkedin")
CONTENT_PLATFORMS: Final[tuple[str, ...]] = (
    "facebook",
    "instagram",
    "tiktok",
    "linkedin",
    "youtube",
)
