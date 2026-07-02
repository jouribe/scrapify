from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, sessionmaker

from scrapyfy.apify_service import ApifyService
from scrapyfy.config import CompanyTarget, Settings, TargetConfig
from scrapyfy.constants import (
    COMMENT_ACTORS,
    COMMENT_IMPORT_PLATFORMS,
    COMMENT_PLATFORMS,
    CONTENT_PLATFORMS,
    POST_ACTORS,
)
from scrapyfy.logging_config import get_logger
from scrapyfy.models import (
    Comment,
    Company,
    Post,
    PostSentimentMetric,
    ScrapeRun,
    SentimentAggregate,
)
from scrapyfy.normalizers import normalize_comment, normalize_post
from scrapyfy.sentiment_service import (
    SentimentService,
    aggregate_sentiment_metrics,
    aggregate_weighted_sentiment,
)

logger = get_logger(__name__)

# If fewer than this fraction of scraped LinkedIn items have a unique URN
# the session cookies are degraded and LinkedIn is only returning cached results.
_LINKEDIN_MIN_UNIQUE_RATIO = 0.15

# When a bad session is detected, subsequent companies use this reduced limit
# to avoid wasting Apify credits while still persisting whatever is available.
_LINKEDIN_BAD_SESSION_LIMIT = 20

# These platforms report resultsLimit as a global cap, not per post.
# To guarantee max_comments_per_post per post we iterate one post at a time.
_PER_POST_COMMENT_PLATFORMS = frozenset({"facebook", "instagram"})


class Pipeline:
    def __init__(
        self,
        settings: Settings,
        targets: TargetConfig,
        service: ApifyService,
        session_factory: sessionmaker[Session],
    ) -> None:
        self.settings = settings
        self.targets = targets
        self.service = service
        self.session_factory = session_factory

    @contextmanager
    def _run_log(self, platform: str, scraper_type: str, actor_id: str):
        with self.session_factory() as session:
            run = ScrapeRun(
                platform=platform,
                scraper_type=scraper_type,
                actor_id=actor_id,
                status="running",
                records_processed=0,
            )
            session.add(run)
            session.commit()
            session.refresh(run)
            logger.info(
                "Run started: run_id=%s platform=%s scraper_type=%s actor_id=%s",
                run.id,
                platform,
                scraper_type,
                actor_id,
            )

            try:
                yield run
                run.status = "success"
            except Exception as error:
                run.status = "failed"
                run.error_message = str(error)
                logger.exception(
                    "Run failed: run_id=%s platform=%s scraper_type=%s",
                    run.id,
                    platform,
                    scraper_type,
                )
                raise
            finally:
                run.finished_at = datetime.now(UTC)
                session.add(run)
                session.commit()
                logger.info(
                    "Run finished: run_id=%s platform=%s scraper_type=%s status=%s",
                    run.id,
                    platform,
                    scraper_type,
                    run.status,
                )

    def run_posts(self, platforms: list[str] | None = None) -> dict[str, int]:
        enabled = self._validate_platforms(platforms or list(POST_ACTORS.keys()), POST_ACTORS)
        summary: dict[str, int] = {}

        for platform in enabled:
            actor_id = POST_ACTORS[platform]
            processed = 0
            linkedin_bad_session = False
            logger.info("Posts extraction started: platform=%s actor_id=%s", platform, actor_id)

            for company in self.targets.companies:
                limit_override: int | None = None
                if platform == "linkedin" and linkedin_bad_session:
                    limit_override = _LINKEDIN_BAD_SESSION_LIMIT
                    logger.info(
                        "LinkedIn session degraded, using reduced limit: company=%s limit=%s",
                        company.slug,
                        limit_override,
                    )

                logger.info(
                    "Executing posts actor: platform=%s company=%s",
                    platform,
                    company.slug,
                )
                actor_input = self.service.build_post_input(
                    platform, company, limit_override=limit_override
                )
                with self._run_log(platform, "posts", actor_id):
                    items = self.service.run_actor(actor_id, actor_input)

                    if platform == "linkedin" and not linkedin_bad_session and items:
                        unique_urns = len({str(it["urn"]) for it in items if it.get("urn")})
                        ratio = unique_urns / len(items)
                        if ratio < _LINKEDIN_MIN_UNIQUE_RATIO:
                            linkedin_bad_session = True
                            logger.warning(
                                "LinkedIn session quality is poor: "
                                "unique_ratio=%.0f%% (%s unique / %s raw). "
                                "Remaining companies will use reduced limit=%s. "
                                "Fix: refresh LINKEDIN_COOKIE_JSON in .env with fresh browser "
                                "cookies (export via 'Cookie Editor' extension in Chrome/Firefox).",
                                ratio * 100,
                                unique_urns,
                                len(items),
                                _LINKEDIN_BAD_SESSION_LIMIT,
                            )

                    processed += self._upsert_posts(platform, company, items)
                    if platform == "linkedin":
                        comment_items = self._extract_linkedin_comments(items)
                        if comment_items:
                            persisted_comments = self._upsert_comments(platform, comment_items)
                            logger.info(
                                "LinkedIn nested comments persisted: company=%s records=%s",
                                company.slug,
                                persisted_comments,
                            )
                        else:
                            logger.info(
                                "LinkedIn nested comments skipped: company=%s reason=no_comments",
                                company.slug,
                            )

            summary[platform] = processed
            logger.info("Posts extraction finished: platform=%s processed=%s", platform, processed)

        return summary

    def run_comments(self, platforms: list[str] | None = None) -> dict[str, int]:
        enabled_raw = platforms or list(COMMENT_ACTORS.keys())
        enabled = [platform for platform in enabled_raw if platform in COMMENT_PLATFORMS]
        enabled = self._validate_platforms(enabled, COMMENT_ACTORS)
        summary: dict[str, int] = {}

        for platform in enabled:
            actor_id = COMMENT_ACTORS[platform]
            processed = 0
            logger.info("Comments extraction started: platform=%s actor_id=%s", platform, actor_id)

            for company in self.targets.companies:
                post_urls = self._fetch_post_urls_for_company(platform, company)
                if not post_urls:
                    logger.info(
                        "Comments extraction skipped: platform=%s company=%s reason=no_post_urls",
                        platform,
                        company.slug,
                    )
                    continue

                logger.info(
                    "Comments extraction: platform=%s company=%s post_urls=%s",
                    platform,
                    company.slug,
                    len(post_urls),
                )

                if platform in _PER_POST_COMMENT_PLATFORMS:
                    # One actor call per post so resultsLimit applies per post, not globally.
                    with self._run_log(platform, "comments", actor_id):
                        for post_url in post_urls:
                            actor_input = self.service.build_comments_input(platform, [post_url])
                            items = self.service.run_actor(actor_id, actor_input)
                            processed += self._upsert_comments(platform, items)
                else:
                    actor_input = self.service.build_comments_input(platform, post_urls)
                    with self._run_log(platform, "comments", actor_id):
                        items = self.service.run_actor(actor_id, actor_input)
                        processed += self._upsert_comments(platform, items)

            summary[platform] = processed
            logger.info(
                "Comments extraction finished: platform=%s processed=%s", platform, processed
            )

        return summary

    def _upsert_posts(
        self,
        platform: str,
        company_target: CompanyTarget,
        items: list[dict[str, Any]],
    ) -> int:
        with self.session_factory() as session:
            company = self._ensure_company(session, company_target)

            # Some actors (notably LinkedIn) can return duplicates in the same dataset.
            # Keep only the last occurrence by external_id to avoid unique constraint errors.
            normalized_by_id: dict[str, dict[str, Any]] = {}
            for item in items:
                normalized = normalize_post(platform, item)
                normalized_by_id[normalized["external_id"]] = normalized

            deduped_items = list(normalized_by_id.values())
            external_ids = [item["external_id"] for item in deduped_items]

            existing_posts = (
                session.execute(
                    select(Post).where(
                        Post.platform == platform, Post.external_id.in_(external_ids)
                    )
                )
                .scalars()
                .all()
            )
            existing_by_id = {post.external_id: post for post in existing_posts}

            processed = 0
            for normalized in deduped_items:
                post = existing_by_id.get(normalized["external_id"])

                if post is None:
                    post = Post(
                        company_id=company.id,
                        platform=platform,
                        external_id=normalized["external_id"],
                        post_url=normalized["post_url"],
                        content=normalized["content"],
                        author=normalized["author"],
                        posted_at=normalized["posted_at"],
                        metrics=normalized["metrics"],
                        raw=normalized["raw"],
                    )
                    session.add(post)
                    existing_by_id[normalized["external_id"]] = post
                else:
                    post.post_url = normalized["post_url"]
                    post.content = normalized["content"]
                    post.author = normalized["author"]
                    post.posted_at = normalized["posted_at"]
                    post.metrics = normalized["metrics"]
                    post.raw = normalized["raw"]

                processed += 1

            session.commit()
            logger.info(
                "Posts upsert completed: platform=%s company=%s records=%s deduped_from=%s",
                platform,
                company_target.slug,
                processed,
                len(items),
            )
            return processed

    def _upsert_comments(self, platform: str, items: list[dict[str, Any]]) -> int:
        with self.session_factory() as session:
            parent_urls = list(
                {
                    url
                    for url in (self._extract_parent_post_url(item) for item in items)
                    if url is not None
                }
            )

            post_by_url: dict[str, Post] = {}
            if parent_urls:
                if platform == "tiktok":
                    # TikTok actor can emit different URL variants per comment item.
                    # Load all TikTok posts and match them using canonical URL form.
                    posts = (
                        session.execute(
                            select(Post).where(
                                Post.platform == platform, Post.post_url.is_not(None)
                            )
                        )
                        .scalars()
                        .all()
                    )
                else:
                    posts = (
                        session.execute(
                            select(Post).where(
                                Post.platform == platform,
                                Post.post_url.in_(parent_urls),
                            )
                        )
                        .scalars()
                        .all()
                    )

                for post in posts:
                    if not post.post_url:
                        continue
                    post_by_url[post.post_url] = post
                    canonical_post_url = self._normalize_url_for_matching(post.post_url)
                    if canonical_post_url:
                        post_by_url[canonical_post_url] = post

            normalized_by_id: dict[str, tuple[dict[str, Any], str | None]] = {}
            for item in items:
                normalized = normalize_comment(platform, item)
                parent_url = self._extract_parent_post_url(item)
                normalized_by_id[normalized["external_id"]] = (normalized, parent_url)

            deduped_items = list(normalized_by_id.values())
            external_ids = [normalized["external_id"] for normalized, _ in deduped_items]

            existing_comments = (
                session.execute(
                    select(Comment).where(
                        Comment.platform == platform,
                        Comment.external_id.in_(external_ids),
                    )
                )
                .scalars()
                .all()
            )
            existing_by_id = {comment.external_id: comment for comment in existing_comments}

            processed = 0
            for normalized, parent_url in deduped_items:
                comment = existing_by_id.get(normalized["external_id"])

                canonical_parent_url = self._normalize_url_for_matching(parent_url)
                post = post_by_url.get(parent_url) or post_by_url.get(canonical_parent_url)
                post_id = post.id if post else None

                if comment is None:
                    comment = Comment(
                        post_id=post_id,
                        platform=platform,
                        external_id=normalized["external_id"],
                        comment_url=normalized["comment_url"],
                        content=normalized["content"],
                        author=normalized["author"],
                        commented_at=normalized["commented_at"],
                        raw=normalized["raw"],
                    )
                    session.add(comment)
                    existing_by_id[normalized["external_id"]] = comment
                else:
                    comment.post_id = post_id
                    comment.comment_url = normalized["comment_url"]
                    comment.content = normalized["content"]
                    comment.author = normalized["author"]
                    comment.commented_at = normalized["commented_at"]
                    comment.raw = normalized["raw"]

                processed += 1

            session.commit()
            logger.info(
                "Comments upsert completed: platform=%s records=%s deduped_from=%s",
                platform,
                processed,
                len(items),
            )
            return processed

    @staticmethod
    def _extract_linkedin_comments(post_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        comment_items: list[dict[str, Any]] = []
        for post in post_items:
            post_url = Pipeline._extract_parent_post_url(post)
            post_urn = post.get("urn")
            comments = post.get("comments")

            if not isinstance(comments, list):
                continue

            for comment in comments:
                if not isinstance(comment, dict):
                    continue

                enriched_comment = dict(comment)
                if post_url and "postUrl" not in enriched_comment:
                    enriched_comment["postUrl"] = post_url
                if post_urn and "postUrn" not in enriched_comment:
                    enriched_comment["postUrn"] = post_urn
                comment_items.append(enriched_comment)

        return comment_items

    @staticmethod
    def _extract_parent_post_url(payload: dict[str, Any]) -> str | None:
        candidates = (
            "postUrl",
            "post_url",
            "pageUrl",
            "url",
            "inputUrl",
            "videoUrl",
            "awemeUrl",
            "webVideoUrl",
            "videoWebUrl",
            "submittedVideoUrl",
            "input",
        )
        for key in candidates:
            value = payload.get(key)
            if value:
                return str(value)
        return None

    @staticmethod
    def _normalize_url_for_matching(url: str | None) -> str | None:
        if not url:
            return None
        try:
            parsed = urlparse(url)
            path = parsed.path.rstrip("/")
            return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}"
        except (TypeError, ValueError):
            return str(url).rstrip("/")

    def _fetch_post_urls_for_company(
        self, platform: str, company_target: CompanyTarget
    ) -> list[str]:
        with self.session_factory() as session:
            rows = session.execute(
                select(Post.post_url)
                .join(Company, Post.company_id == Company.id)
                .where(
                    Post.platform == platform,
                    Post.post_url.is_not(None),
                    Company.slug == company_target.slug,
                )
            ).scalars()
            return list(dict.fromkeys([value for value in rows if value]))

    @staticmethod
    def _ensure_company(session: Session, company_target: CompanyTarget) -> Company:
        stmt = pg_insert(Company).values(name=company_target.name, slug=company_target.slug)
        stmt = stmt.on_conflict_do_update(
            index_elements=["slug"],
            set_={"name": company_target.name},
        )
        session.execute(stmt)
        session.commit()
        entity = session.execute(
            select(Company).where(Company.slug == company_target.slug)
        ).scalar_one()
        session.refresh(entity)
        return entity

    def import_linkedin_dataset(self, dataset_id: str) -> dict[str, int]:
        """Fetch an existing Apify dataset by ID and persist its LinkedIn posts + comments."""
        items = self.service.fetch_dataset_items(dataset_id)
        logger.info(
            "LinkedIn dataset import started: dataset_id=%s total_items=%s",
            dataset_id,
            len(items),
        )

        company_by_slug: dict[str, CompanyTarget] = {}
        for company in self.targets.companies:
            slug = self._normalize_linkedin_slug(company.handles.linkedin)
            if slug:
                company_by_slug[slug] = company

        groups: dict[str, list[dict[str, Any]]] = {}
        unmatched_count = 0
        for item in items:
            slug = self._detect_linkedin_company_slug(item, company_by_slug)
            if slug:
                groups.setdefault(slug, []).append(item)
            else:
                unmatched_count += 1

        if unmatched_count:
            logger.warning(
                "LinkedIn dataset import: %s items could not be matched to any company target. "
                "Verify that 'authorProfile' values in the dataset match your "
                "config/targets.yaml handles.",
                unmatched_count,
            )

        total_posts = 0
        total_comments = 0
        actor_ref = f"dataset:{dataset_id}"

        for slug, group_items in groups.items():
            company_target = company_by_slug[slug]
            logger.info(
                "LinkedIn dataset import: persisting company=%s posts=%s",
                slug,
                len(group_items),
            )
            with self._run_log("linkedin", "dataset_import", actor_ref):
                total_posts += self._upsert_posts("linkedin", company_target, group_items)
                comment_items = self._extract_linkedin_comments(group_items)
                if comment_items:
                    total_comments += self._upsert_comments("linkedin", comment_items)

        logger.info(
            "LinkedIn dataset import finished: dataset_id=%s posts=%s comments=%s unmatched=%s",
            dataset_id,
            total_posts,
            total_comments,
            unmatched_count,
        )
        return {"posts": total_posts, "comments": total_comments, "unmatched": unmatched_count}

    def import_local_posts_file(
        self, file_path: str, platform: str, company_slug: str
    ) -> dict[str, int]:
        """Import posts from a local JSON file for a specific company.

        Native TikTok API format (items with ``author`` dict and ``stats`` dict)
        is automatically adapted to the keys expected by ``normalize_post``.
        """
        raw = Path(file_path).read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError(f"Expected a JSON array in {file_path}, got {type(data).__name__}")

        company_target = next((c for c in self.targets.companies if c.slug == company_slug), None)
        if company_target is None:
            raise ValueError(
                f"Company slug '{company_slug}' not found in targets.yaml. "
                f"Available slugs: {[c.slug for c in self.targets.companies]}"
            )

        if platform == "tiktok":
            items = [self._adapt_native_tiktok_post(item) for item in data]
        else:
            items = data

        file_ref = f"local_file:{Path(file_path).name}"
        with self._run_log(platform, "local_file_import", file_ref):
            count = self._upsert_posts(platform, company_target, items)

        logger.info(
            "Local file import finished: platform=%s company=%s file=%s posts=%s",
            platform,
            company_slug,
            file_path,
            count,
        )
        return {"posts": count}

    @staticmethod
    def _adapt_native_tiktok_post(item: dict[str, Any]) -> dict[str, Any]:
        """Transform native TikTok API response format to normalized field names.

        The native API returns metrics nested under ``stats``, the author as a
        sub-object, and ``createTime`` as a Unix timestamp.  This helper flattens
        those values so that ``normalize_post`` can pick them up without changes.
        """
        author = item.get("author") or {}
        unique_id = author.get("uniqueId", "") if isinstance(author, dict) else ""
        nickname = author.get("nickname", "") if isinstance(author, dict) else ""
        video_id = item.get("id", "")

        stats = item.get("stats") or {}
        stats_v2 = item.get("statsV2") or {}

        def _stat(key: str) -> int | None:
            v = stats.get(key)
            if v is not None:
                return int(v)
            v2 = stats_v2.get(key)
            return int(v2) if v2 is not None else None

        create_time = item.get("createTime")
        posted_at_iso: str | None = None
        if create_time:
            try:
                posted_at_iso = datetime.fromtimestamp(int(create_time), tz=UTC).isoformat()
            except (TypeError, ValueError, OSError):
                pass

        return {
            **item,
            "webVideoUrl": (
                f"https://www.tiktok.com/@{unique_id}/video/{video_id}"
                if unique_id and video_id
                else item.get("webVideoUrl")
            ),
            "description": item.get("desc") or item.get("description"),
            "authorName": nickname or item.get("authorName"),
            "createTimeISO": posted_at_iso or item.get("createTimeISO"),
            "diggCount": _stat("diggCount"),
            "commentCount": _stat("commentCount"),
            "shareCount": _stat("shareCount"),
            "playCount": _stat("playCount"),
        }

    def import_posts_dataset(self, platform: str, dataset_id: str) -> dict[str, int]:
        """Import posts from an existing Apify dataset for any supported post platform."""
        enabled = self._validate_platforms([platform], {p: p for p in CONTENT_PLATFORMS})
        selected_platform = enabled[0]

        if selected_platform == "linkedin":
            return self.import_linkedin_dataset(dataset_id)

        items = self.service.fetch_dataset_items(dataset_id)
        logger.info(
            "Posts dataset import started: platform=%s dataset_id=%s total_items=%s",
            selected_platform,
            dataset_id,
            len(items),
        )

        groups: dict[str, list[dict[str, Any]]] = {}
        unmatched_count = 0
        for item in items:
            company_slug = self._detect_company_slug_for_platform(item, selected_platform)
            if company_slug:
                groups.setdefault(company_slug, []).append(item)
            else:
                unmatched_count += 1

        if unmatched_count:
            logger.warning(
                "Posts dataset import: %s items could not be matched to any company target "
                "for platform=%s. Verify handles in config/targets.yaml and dataset fields.",
                unmatched_count,
                selected_platform,
            )

        actor_ref = f"dataset:{dataset_id}"
        total_posts = 0
        for company in self.targets.companies:
            company_items = groups.get(company.slug, [])
            if not company_items:
                continue

            with self._run_log(selected_platform, "dataset_import_posts", actor_ref):
                total_posts += self._upsert_posts(selected_platform, company, company_items)

        logger.info(
            "Posts dataset import finished: platform=%s dataset_id=%s posts=%s unmatched=%s",
            selected_platform,
            dataset_id,
            total_posts,
            unmatched_count,
        )
        return {
            "posts": total_posts,
            "unmatched": unmatched_count,
        }

    def import_comments_dataset(
        self,
        platform: str,
        company_slug: str,
        dataset_id: str,
    ) -> dict[str, int]:
        """Import comments from an existing Apify dataset without rerunning actors."""
        enabled = self._validate_platforms([platform], {p: p for p in COMMENT_IMPORT_PLATFORMS})
        selected_platform = enabled[0]

        company_target = next(
            (company for company in self.targets.companies if company.slug == company_slug),
            None,
        )
        if company_target is None:
            raise ValueError(f"Company not found: {company_slug}")

        items = self.service.fetch_dataset_items(dataset_id)
        logger.info(
            "Comments dataset import started: platform=%s company=%s dataset_id=%s items=%s",
            selected_platform,
            company_slug,
            dataset_id,
            len(items),
        )

        post_urls = self._fetch_post_urls_for_company(selected_platform, company_target)
        normalized_post_urls = {
            value
            for value in (self._normalize_url_for_matching(url) for url in post_urls)
            if value is not None
        }

        filtered_items: list[dict[str, Any]] = []
        skipped_items = 0
        for item in items:
            parent_url = self._extract_parent_post_url(item)
            normalized_parent = self._normalize_url_for_matching(parent_url)
            if normalized_parent is None:
                skipped_items += 1
                continue

            if normalized_post_urls and normalized_parent not in normalized_post_urls:
                skipped_items += 1
                continue

            filtered_items.append(item)

        actor_ref = f"dataset:{dataset_id}"
        with self._run_log(selected_platform, "dataset_import_comments", actor_ref):
            upserted = self._upsert_comments(selected_platform, filtered_items)

        logger.info(
            "Comments dataset import finished: platform=%s company=%s dataset_id=%s "
            "dataset_items=%s filtered_items=%s skipped_items=%s upserted=%s",
            selected_platform,
            company_slug,
            dataset_id,
            len(items),
            len(filtered_items),
            skipped_items,
            upserted,
        )
        return {
            "dataset_items": len(items),
            "filtered_items": len(filtered_items),
            "skipped_items": skipped_items,
            "upserted": upserted,
        }

    @staticmethod
    def _normalize_linkedin_slug(handle: str | None) -> str | None:
        if not isinstance(handle, str):
            return None
        normalized = handle.strip()
        if not normalized:
            return None
        if "linkedin.com/company/" in normalized:
            return normalized.rstrip("/").split("/company/")[-1].lower()
        return normalized.lstrip("/").lower()

    @staticmethod
    def _detect_linkedin_company_slug(
        item: dict[str, Any],
        company_by_slug: dict[str, CompanyTarget],
    ) -> str | None:
        candidate_keys = ("authorProfile", "pageUrl", "companyUrl", "foundPageUrl", "inputUrl")
        for key in candidate_keys:
            value = item.get(key)
            if not isinstance(value, str) or "linkedin.com/company/" not in value:
                continue
            slug = value.rstrip("/").split("/company/")[-1].lower()
            if slug in company_by_slug:
                return slug
        return None

    def _detect_company_slug_for_platform(
        self,
        item: dict[str, Any],
        platform: str,
    ) -> str | None:
        company_tokens: dict[str, set[str]] = {
            company.slug: self._build_company_tokens(company, platform)
            for company in self.targets.companies
        }
        signals = self._extract_item_signals(item, platform)

        scored: list[tuple[str, int]] = []
        for slug, tokens in company_tokens.items():
            score = sum(1 for token in tokens if any(token in signal for signal in signals))
            if score > 0:
                scored.append((slug, score))

        if not scored:
            return None

        scored.sort(key=lambda pair: pair[1], reverse=True)
        top_slug, top_score = scored[0]
        ties = [slug for slug, score in scored if score == top_score]
        if len(ties) > 1:
            return None
        return top_slug

    @staticmethod
    def _build_company_tokens(company: CompanyTarget, platform: str) -> set[str]:
        raw_handle = getattr(company.handles, platform, None)
        if not raw_handle:
            return set()
        return Pipeline._tokens_from_text(raw_handle)

    @staticmethod
    def _extract_item_signals(item: dict[str, Any], platform: str) -> set[str]:
        values: list[str] = []
        common_keys = (
            "inputUrl",
            "url",
            "postUrl",
            "pageUrl",
            "profileUrl",
            "channelUrl",
            "authorProfile",
            "authorName",
            "authorChannelName",
            "authorChannelId",
            "channelName",
            "channelTitle",
            "user",
            "username",
            "uploader",
            "uploaderName",
            "pageName",
        )
        for key in common_keys:
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                values.append(value)

        if platform == "instagram":
            for key in ("ownerUsername", "authorUsername", "profileName"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    values.append(value)

        if platform == "tiktok":
            author_meta = item.get("authorMeta")
            if isinstance(author_meta, dict):
                for key in ("name", "nickName"):
                    value = author_meta.get(key)
                    if isinstance(value, str) and value.strip():
                        values.append(value)
            for key in ("authorUsername", "uniqueId"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    values.append(value)

        if platform == "youtube":
            for key in ("channelName", "channelTitle", "authorName", "uploader", "uploaderName"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    values.append(value)

        signals: set[str] = set()
        for value in values:
            signals.update(Pipeline._tokens_from_text(value))
        return signals

    @staticmethod
    def _tokens_from_text(text: str) -> set[str]:
        lowered = unquote(text).lower().strip()
        if not lowered:
            return set()

        blacklist = {
            "https",
            "http",
            "www",
            "com",
            "facebook",
            "instagram",
            "linkedin",
            "tiktok",
            "company",
        }

        tokens: set[str] = {lowered}
        if "@" in lowered:
            for part in lowered.split("@"):
                if part:
                    tokens.add(part)

        try:
            parsed = urlparse(lowered)
            if parsed.netloc:
                netloc = parsed.netloc
                if netloc.startswith("www."):
                    netloc = netloc[4:]
                tokens.add(netloc)
                tokens.update([seg for seg in netloc.split(".") if seg])
            if parsed.path:
                path = parsed.path.strip("/")
                if path:
                    tokens.add(path)
                    tokens.update([seg for seg in path.split("/") if seg])
        except ValueError:
            pass

        cleaned_tokens: set[str] = set()
        for token in tokens:
            normalized = token.strip("@/ ")
            if len(normalized) < 3:
                continue
            if normalized in blacklist:
                continue
            cleaned_tokens.add(normalized)
        return cleaned_tokens

    @staticmethod
    def _validate_platforms(selected: list[str], supported: dict[str, str]) -> list[str]:
        invalid = [platform for platform in selected if platform not in supported]
        if invalid:
            supported_values = ", ".join(sorted(supported.keys()))
            invalid_values = ", ".join(sorted(invalid))
            raise ValueError(f"Invalid platforms: {invalid_values}. Supported: {supported_values}")
        return selected

    def run_sentiment(
        self, platforms: list[str] | None = None, company_slug: str | None = None
    ) -> dict[str, int]:
        """
        Analyze sentiment of comments and aggregate metrics by post, platform+company, and company.

        Returns counts of posts analyzed and aggregates generated.
        """
        enabled = platforms or list(CONTENT_PLATFORMS)
        enabled = self._validate_platforms(enabled, {p: p for p in CONTENT_PLATFORMS})

        sentiment_service = SentimentService(
            model_id=self.settings.sentiment_model_id,
            device=self.settings.sentiment_device,
            batch_size=self.settings.sentiment_batch_size,
        )

        posts_analyzed = 0
        aggregates_created = 0
        logger.info(
            "Sentiment analysis started: platforms=%s company=%s",
            ",".join(enabled),
            company_slug,
        )

        with self._run_log("sentiment", "sentiment_analysis", self.settings.sentiment_model_id):
            with self.session_factory() as session:
                # Build company filter if specified
                companies_to_process = self.targets.companies
                if company_slug:
                    companies_to_process = [
                        c for c in self.targets.companies if c.slug == company_slug
                    ]
                    if not companies_to_process:
                        logger.warning("Company not found: slug=%s", company_slug)
                        return {"posts_analyzed": 0, "aggregates_created": 0}

                for platform in enabled:
                    for company in companies_to_process:
                        # Fetch posts and their comments for this platform+company
                        posts_with_comments = self._fetch_posts_with_comments(
                            session, platform, company
                        )
                        if not posts_with_comments:
                            logger.info(
                                "Sentiment analysis skipped: platform=%s company=%s "
                                "reason=no_posts",
                                platform,
                                company.slug,
                            )
                            continue

                        logger.info(
                            "Sentiment analysis: platform=%s company=%s posts=%s",
                            platform,
                            company.slug,
                            len(posts_with_comments),
                        )

                        # Process each post's comments
                        platform_metrics: list[dict[str, Any]] = []

                        for post_id, comments in posts_with_comments.items():
                            # Analyze comments for this post
                            valid_comments = [
                                c
                                for c in comments
                                if c.get("content") and str(c.get("content", "")).strip()
                            ]

                            # Run sentiment analysis (or empty result when there is no comment text)
                            analyzed = sentiment_service.analyze_comments(valid_comments)
                            analyzed_comments = [c for c, _ in analyzed]

                            # Persist sentiment fields in each comment.raw
                            for analyzed_comment in analyzed_comments:
                                comment_id = analyzed_comment.get("id")
                                if not comment_id:
                                    continue

                                comment_obj = session.get(Comment, comment_id)
                                if not comment_obj:
                                    continue

                                raw_payload = dict(comment_obj.raw or {})
                                raw_payload.update(
                                    {
                                        "sentiment_label": analyzed_comment.get("sentiment_label"),
                                        "sentiment_score": analyzed_comment.get("sentiment_score"),
                                        "sentiment_source": analyzed_comment.get(
                                            "sentiment_source"
                                        ),
                                    }
                                )
                                comment_obj.raw = raw_payload
                                session.add(comment_obj)

                            # Aggregate sentiment metrics for this post
                            post_sentiment = aggregate_sentiment_metrics(
                                analyzed_comments, len(valid_comments)
                            )

                            dominant_label = self._post_sentiment_label(post_sentiment)
                            post_sentiment_flat = {
                                "sentiment_label": dominant_label,
                                "sentiment_score": post_sentiment.get("avg_confidence", 0.0),
                                "positive_count": post_sentiment.get("positive_count", 0),
                                "neutral_count": post_sentiment.get("neutral_count", 0),
                                "negative_count": post_sentiment.get("negative_count", 0),
                                "valid_comments": post_sentiment.get("valid_comments", 0),
                                "net_sentiment": post_sentiment.get("net_sentiment", 0.0),
                            }

                            # Update post metrics
                            post = session.get(Post, post_id)
                            if post:
                                current_metrics = dict(post.metrics or {})
                                current_metrics.update(post_sentiment_flat)
                                current_metrics["sentiment"] = post_sentiment
                                post.metrics = current_metrics
                                session.add(post)

                                post_metric_stmt = pg_insert(PostSentimentMetric).values(
                                    post_id=post.id,
                                    company_id=post.company_id,
                                    platform=post.platform,
                                    metrics=post_sentiment,
                                    model_name=self.settings.sentiment_model_id,
                                )
                                post_metric_stmt = post_metric_stmt.on_conflict_do_update(
                                    index_elements=["post_id"],
                                    set_={
                                        "company_id": post.company_id,
                                        "platform": post.platform,
                                        "metrics": post_sentiment,
                                        "model_name": self.settings.sentiment_model_id,
                                        "computed_at": datetime.now(UTC),
                                    },
                                )
                                session.execute(post_metric_stmt)

                                posts_analyzed += 1
                                platform_metrics.append(post_sentiment)

                        session.commit()

                        # Create aggregates for this platform+company
                        if platform_metrics:
                            # Aggregate weighted by valid_comments for this platform
                            platform_agg = aggregate_weighted_sentiment(platform_metrics)
                            platform_agg["total_posts"] = len(platform_metrics)

                            # Persist platform aggregate
                            company_obj = session.execute(
                                select(Company).where(Company.slug == company.slug)
                            ).scalar_one()

                            stmt = pg_insert(SentimentAggregate).values(
                                company_id=company_obj.id,
                                scope="platform_company",
                                platform=platform,
                                metrics=platform_agg,
                                model_name=self.settings.sentiment_model_id,
                            )
                            stmt = stmt.on_conflict_do_update(
                                index_elements=["company_id", "platform", "scope"],
                                set_={"metrics": platform_agg, "computed_at": datetime.now(UTC)},
                            )
                            session.execute(stmt)
                            aggregates_created += 1

                session.commit()

                # Create global company aggregates (across all platforms for each company)
                for company in companies_to_process:
                    company_obj = session.execute(
                        select(Company).where(Company.slug == company.slug)
                    ).scalar_one()

                    # Fetch all posts for this company and extract those with sentiment metrics.
                    all_posts = (
                        session.execute(
                            select(Post).where(
                                Post.company_id == company_obj.id,
                                Post.platform.in_(enabled),
                            )
                        )
                        .scalars()
                        .all()
                    )

                    all_post_metrics = []
                    for post in all_posts:
                        if post.metrics and "sentiment" in post.metrics:
                            all_post_metrics.append(post.metrics["sentiment"])

                    if all_post_metrics:
                        global_agg = aggregate_weighted_sentiment(all_post_metrics)
                        global_agg["total_posts"] = len(all_post_metrics)

                        stmt = pg_insert(SentimentAggregate).values(
                            company_id=company_obj.id,
                            scope="company_global",
                            platform="all",
                            metrics=global_agg,
                            model_name=self.settings.sentiment_model_id,
                        )
                        stmt = stmt.on_conflict_do_update(
                            index_elements=["company_id", "platform", "scope"],
                            set_={"metrics": global_agg, "computed_at": datetime.now(UTC)},
                        )
                        session.execute(stmt)
                        aggregates_created += 1

                session.commit()

        logger.info(
            "Sentiment analysis finished: posts_analyzed=%s aggregates=%s",
            posts_analyzed,
            aggregates_created,
        )
        return {"posts_analyzed": posts_analyzed, "aggregates_created": aggregates_created}

    @staticmethod
    def _dominant_sentiment_label(post_sentiment: dict[str, Any]) -> str:
        counts = {
            "POSITIVE": int(post_sentiment.get("positive_count", 0)),
            "NEUTRAL": int(post_sentiment.get("neutral_count", 0)),
            "NEGATIVE": int(post_sentiment.get("negative_count", 0)),
        }
        max_count = max(counts.values())
        leaders = [label for label, count in counts.items() if count == max_count]
        return leaders[0] if len(leaders) == 1 else "NEUTRAL"

    @staticmethod
    def _post_sentiment_label(post_sentiment: dict[str, Any]) -> str:
        if int(post_sentiment.get("valid_comments", 0)) == 0:
            return "NO_DATA"
        return Pipeline._dominant_sentiment_label(post_sentiment)

    def _fetch_posts_with_comments(
        self, session: Session, platform: str, company_target: CompanyTarget
    ) -> dict[int, list[dict[str, Any]]]:
        """
        Fetch posts with their associated comments for a platform+company.

        Returns dict mapping post_id -> list of comments (as dicts).
        """
        company_obj = session.execute(
            select(Company).where(Company.slug == company_target.slug)
        ).scalar_one()

        posts = (
            session.execute(
                select(Post).where(Post.company_id == company_obj.id, Post.platform == platform)
            )
            .scalars()
            .all()
        )

        result: dict[int, list[dict[str, Any]]] = {}
        for post in posts:
            comments = (
                session.execute(select(Comment).where(Comment.post_id == post.id)).scalars().all()
            )

            comment_dicts = [
                {
                    "id": c.id,
                    "content": c.content,
                    "author": c.author,
                    "external_id": c.external_id,
                    "raw": c.raw,
                }
                for c in comments
            ]
            result[post.id] = comment_dicts

        return result
