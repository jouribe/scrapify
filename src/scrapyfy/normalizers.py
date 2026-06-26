from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from dateutil.parser import parse as parse_datetime


def _pick(payload: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in payload and payload[key] not in (None, ""):
            return payload[key]
    return None


def _safe_dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value

    try:
        if isinstance(value, (int, float)):
            timestamp = float(value)
            if timestamp > 1_000_000_000_000:
                timestamp /= 1000
            return datetime.fromtimestamp(timestamp, tz=UTC)

        text_value = str(value).strip()
        if text_value.isdigit():
            timestamp = float(text_value)
            if timestamp > 1_000_000_000_000:
                timestamp /= 1000
            return datetime.fromtimestamp(timestamp, tz=UTC)

        return parse_datetime(text_value)
    except (TypeError, ValueError, OverflowError):
        return None


def _fallback_id(platform: str, payload: dict[str, Any], suffix: str) -> str:
    seed = f"{platform}:{suffix}:{payload}".encode()
    return hashlib.sha256(seed).hexdigest()


def normalize_post(platform: str, payload: dict[str, Any]) -> dict[str, Any]:
    external_id = _pick(
        payload,
        ("id", "postId", "post_id", "urn", "shortCode", "aweme_id", "videoId", "video_id"),
    )
    post_url = _pick(
        payload,
        (
            "url",
            "postUrl",
            "post_url",
            "inputUrl",
            "webVideoUrl",
            "videoUrl",
            "permalink",
        ),
    )
    author = _pick(
        payload,
        (
            "authorName",
            "authorUsername",
            "ownerUsername",
            "username",
            "profileName",
            "channelName",
            "channelTitle",
            "authorChannelName",
            "uploader",
            "uploaderName",
            "author",
        ),
    )
    content = _pick(payload, ("text", "caption", "description", "content", "message", "title"))
    posted_at = _safe_dt(
        _pick(
            payload,
            (
                "createTimeISO",
                "createdAt",
                "takenAt",
                "time",
                "publishedAt",
                "publishedAtISO",
                "postedAtISO",
                "postedAt",
                "date",
                "timestamp",
                "postedAtTimestamp",
            ),
        )
    )

    metrics = {
        "likes": _pick(
            payload,
            ("likesCount", "likeCount", "diggCount", "likes", "reactionsCount", "numLikes"),
        ),
        "comments": _pick(payload, ("commentsCount", "commentCount", "numComments")),
        "shares": _pick(payload, ("sharesCount", "shareCount", "shares", "numShares")),
        "views": _pick(
            payload,
            ("playCount", "viewsCount", "viewCount", "views", "numImpressions"),
        ),
    }

    normalized_external_id = (
        str(external_id) if external_id else _fallback_id(platform, payload, "post")
    )

    return {
        "external_id": normalized_external_id,
        "post_url": str(post_url) if post_url else None,
        "content": str(content) if content else None,
        "author": str(author) if author else None,
        "posted_at": posted_at,
        "metrics": metrics,
        "raw": payload,
    }


def normalize_comment(platform: str, payload: dict[str, Any]) -> dict[str, Any]:
    external_id = _pick(
        payload,
        (
            "id",
            "commentId",
            "comment_id",
            "cid",
            "pk",
            "urn",
            "commentUrn",
            "link",
        ),
    )
    comment_url = _pick(payload, ("url", "commentUrl", "comment_url", "permalink", "link"))
    author = _pick(payload, ("ownerUsername", "authorUsername", "username", "authorName", "author"))

    if isinstance(author, dict):
        first_name = str(author.get("firstName", "")).strip()
        last_name = str(author.get("lastName", "")).strip()
        full_name = f"{first_name} {last_name}".strip()
        author = full_name or author.get("publicId") or author.get("profileId")

    content = _pick(payload, ("text", "commentText", "comment", "message", "content"))
    commented_at = _safe_dt(
        _pick(payload, ("timestamp", "createdAt", "createTimeISO", "time", "publishedAt"))
    )

    normalized_external_id = (
        str(external_id) if external_id else _fallback_id(platform, payload, "comment")
    )

    return {
        "external_id": normalized_external_id,
        "comment_url": str(comment_url) if comment_url else None,
        "content": str(content) if content else None,
        "author": str(author) if author else None,
        "commented_at": commented_at,
        "raw": payload,
    }
