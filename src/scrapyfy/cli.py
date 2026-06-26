from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import typer
import yaml

from scrapyfy.apify_service import ApifyService
from scrapyfy.config import Paths, Settings, load_targets
from scrapyfy.constants import (
    COMMENT_IMPORT_PLATFORMS,
    COMMENT_PLATFORMS,
    CONTENT_PLATFORMS,
    PLATFORMS,
)
from scrapyfy.db import build_engine, build_session_factory, session_scope
from scrapyfy.excel_service import ExcelReportService
from scrapyfy.logging_config import configure_logging, get_logger
from scrapyfy.models import Base
from scrapyfy.pipeline import Pipeline

app = typer.Typer(help="Apify scraping pipeline for Facebook, Instagram, TikTok and LinkedIn")
logger = get_logger(__name__)


def _generate_slug(name: str) -> str:
    """Generate slug from company name: remove accents, lowercase, replace spaces with hyphens."""
    # Remove accents
    normalized = unicodedata.normalize("NFKD", name)
    slug = "".join([c for c in normalized if not unicodedata.combining(c)])
    # Convert to lowercase and replace spaces/special chars with hyphens
    slug = re.sub(r"[^a-z0-9]+", "-", slug.lower()).strip("-")
    return slug


def _bootstrap() -> tuple[Settings, Pipeline]:
    root = Path.cwd()
    settings = Settings()
    paths = Paths(root=root)
    configure_logging(paths.logs_dir, settings.log_level, settings.log_file)
    targets = load_targets(paths)
    service = ApifyService(settings=settings, paths=paths)
    session_factory = build_session_factory(settings)
    pipeline = Pipeline(
        settings=settings,
        targets=targets,
        service=service,
        session_factory=session_factory,
    )
    return settings, pipeline


def _parse_platforms(value: str, allowed: set[str]) -> list[str]:
    selected = [item.strip() for item in value.split(",") if item.strip()]
    invalid = [item for item in selected if item not in allowed]
    if invalid:
        raise typer.BadParameter(
            f"Invalid platforms: {', '.join(invalid)}. Allowed: {', '.join(sorted(allowed))}"
        )
    return selected


def _parse_company_slugs(value: str) -> list[str]:
    cleaned = value.strip()
    if cleaned.startswith("[") and cleaned.endswith("]"):
        cleaned = cleaned[1:-1]

    selected = [item.strip() for item in cleaned.split(",") if item.strip()]
    if not selected:
        raise typer.BadParameter("Provide at least one company slug")
    return selected


@app.command("init-db")
def init_db() -> None:
    """Create database tables if they do not exist."""
    settings = Settings()
    root = Path.cwd()
    paths = Paths(root=root)
    configure_logging(paths.logs_dir, settings.log_level, settings.log_file)
    engine = build_engine(settings)
    Base.metadata.create_all(engine)
    logger.info("Database schema is ready")
    typer.echo("Database schema ready")


@app.command("run-posts")
def run_posts(platforms: str = typer.Option("facebook,instagram,tiktok,linkedin")) -> None:
    """Run post scrapers."""
    _, pipeline = _bootstrap()
    selected = _parse_platforms(platforms, set(PLATFORMS))
    logger.info("Running posts pipeline for platforms: %s", ",".join(selected))
    summary = pipeline.run_posts(selected)
    logger.info("Posts pipeline finished: %s", summary)
    typer.echo(summary)


@app.command("run-comments")
def run_comments(platforms: str = typer.Option("facebook,instagram,tiktok")) -> None:
    """Run comments scrapers for posts already persisted."""
    _, pipeline = _bootstrap()
    selected = _parse_platforms(platforms, COMMENT_PLATFORMS)
    logger.info("Running comments pipeline for platforms: %s", ",".join(selected))
    summary = pipeline.run_comments(selected)
    logger.info("Comments pipeline finished: %s", summary)
    typer.echo(summary)


@app.command("run-all")
def run_all() -> None:
    """Run posts first and then comments."""
    _, pipeline = _bootstrap()
    logger.info("Running complete pipeline")
    posts_summary = pipeline.run_posts(["facebook", "instagram", "tiktok", "linkedin"])
    comments_summary = pipeline.run_comments(["facebook", "instagram", "tiktok"])
    logger.info("Complete pipeline finished. posts=%s comments=%s", posts_summary, comments_summary)
    typer.echo({"posts": posts_summary, "comments": comments_summary})


@app.command("import-linkedin-dataset")
def import_linkedin_dataset(
    dataset_id: str = typer.Argument(help="Apify dataset ID to import from"),
) -> None:
    """Import LinkedIn posts and nested comments from an existing Apify dataset."""
    _, pipeline = _bootstrap()
    logger.info("Importing LinkedIn dataset: dataset_id=%s", dataset_id)
    summary = pipeline.import_linkedin_dataset(dataset_id)
    logger.info("LinkedIn dataset import finished: %s", summary)
    typer.echo(summary)


@app.command("import-posts-dataset")
def import_posts_dataset(
    dataset_id: str = typer.Argument(help="Apify dataset ID to import posts from"),
    platform: str = typer.Option(
        ...,
        help="Posts platform (facebook, instagram, tiktok, linkedin, youtube)",
    ),
) -> None:
    """Import posts from an existing Apify dataset for any supported platform."""
    _, pipeline = _bootstrap()
    if platform not in set(CONTENT_PLATFORMS):
        raise typer.BadParameter(
            f"Invalid platform: {platform}. Allowed: {', '.join(sorted(set(CONTENT_PLATFORMS)))}"
        )

    logger.info(
        "Importing posts dataset: platform=%s dataset_id=%s",
        platform,
        dataset_id,
    )
    summary = pipeline.import_posts_dataset(platform=platform, dataset_id=dataset_id)
    logger.info("Posts dataset import finished: %s", summary)
    typer.echo(summary)


@app.command("run-sentiment")
def run_sentiment(
    platforms: str = typer.Option(
        "facebook,instagram,tiktok,linkedin,youtube",
        help="Comma-separated list of platforms to analyze",
    ),
    company_slug: str | None = typer.Option(
        None, help="Optional: analyze only a specific company by slug"
    ),
) -> None:
    """Analyze sentiment of comments and generate aggregated metrics."""
    _, pipeline = _bootstrap()
    selected = _parse_platforms(platforms, set(CONTENT_PLATFORMS))
    logger.info(
        "Running sentiment analysis: platforms=%s company=%s",
        ",".join(selected),
        company_slug,
    )
    summary = pipeline.run_sentiment(selected, company_slug=company_slug)
    logger.info("Sentiment analysis finished: %s", summary)
    typer.echo(summary)


@app.command("import-local-posts")
def import_local_posts(
    file_path: str = typer.Argument(help="Path to local JSON file with posts"),
    platform: str = typer.Option(
        ..., help="Platform (facebook, instagram, tiktok, linkedin, youtube)"
    ),
    company_slug: str = typer.Option(..., help="Company slug from targets.yaml"),
) -> None:
    """Import posts from a local JSON file for a specific company.

    Supports native TikTok API format (the format produced by non-Apify scrapers)
    as well as the Apify actor output format used by other platforms.
    """
    _, pipeline = _bootstrap()
    if platform not in set(CONTENT_PLATFORMS):
        raise typer.BadParameter(
            f"Invalid platform: {platform}. Allowed: {', '.join(sorted(set(CONTENT_PLATFORMS)))}"
        )

    logger.info(
        "Importing local posts file: platform=%s company=%s file=%s",
        platform,
        company_slug,
        file_path,
    )
    summary = pipeline.import_local_posts_file(
        file_path=file_path, platform=platform, company_slug=company_slug
    )
    logger.info("Local posts import finished: %s", summary)
    typer.echo(summary)


@app.command("import-comments-dataset")
def import_comments_dataset(
    dataset_id: str = typer.Argument(help="Apify dataset ID to import comments from"),
    company_slug: str = typer.Option(..., help="Company slug (e.g., caja-arequipa)"),
    platform: str = typer.Option(
        "tiktok", help="Comments platform (facebook, instagram, tiktok, youtube)"
    ),
) -> None:
    """Import comments from an existing Apify dataset without rerunning actors."""
    _, pipeline = _bootstrap()
    if platform not in set(COMMENT_IMPORT_PLATFORMS):
        raise typer.BadParameter(
            f"Invalid platform: {platform}. Allowed: {', '.join(sorted(set(COMMENT_IMPORT_PLATFORMS)))}"
        )

    logger.info(
        "Importing comments dataset: platform=%s company=%s dataset_id=%s",
        platform,
        company_slug,
        dataset_id,
    )
    summary = pipeline.import_comments_dataset(
        platform=platform,
        company_slug=company_slug,
        dataset_id=dataset_id,
    )
    logger.info("Comments dataset import finished: %s", summary)
    typer.echo(summary)


@app.command("list-comment-links")
def list_comment_links(
    platform: str | None = typer.Option(
        None, help="Filter by platform (facebook, instagram, tiktok)"
    ),
    company_slug: str | None = typer.Option(None, help="Filter by company slug"),
) -> None:
    """List comment links grouped by platform and company, separated by newlines."""
    settings = Settings()
    root = Path.cwd()
    paths = Paths(root=root)
    configure_logging(paths.logs_dir, settings.log_level, settings.log_file)

    from scrapyfy.models import Comment, Company, Post

    session_factory = build_session_factory(settings)

    with session_scope(session_factory) as session:
        # Build query with explicit filtering
        query = (
            session.query(Company.slug, Post.platform, Comment.comment_url)
            .join(Post, Comment.post_id == Post.id)
            .join(Company, Post.company_id == Company.id)
            .filter(Comment.comment_url.isnot(None))
        )

        # Apply filters
        if platform:
            query = query.filter(Post.platform == platform)
        if company_slug:
            query = query.filter(Company.slug == company_slug)

        results = query.all()

        if not results:
            typer.echo("No comments found with the specified filters.")
            return

        # Group by platform and company
        grouped = {}
        for company, plt, url in results:
            key = f"{plt.upper()} - {company}"
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(url)

        # Output grouped results
        for key in sorted(grouped.keys()):
            typer.echo(f"\n{key}:")
            for url in grouped[key]:
                typer.echo(url)

    logger.info(
        "Comment links listed: platform=%s company=%s results=%d",
        platform,
        company_slug,
        len(results),
    )


@app.command("list-post-links")
def list_post_links(
    platform: str | None = typer.Option(
        None, help="Filter by platform (facebook, instagram, tiktok, linkedin, youtube)"
    ),
    company_slug: str | None = typer.Option(None, help="Filter by company slug"),
) -> None:
    """List post links grouped by platform and company, separated by newlines."""
    settings = Settings()
    root = Path.cwd()
    paths = Paths(root=root)
    configure_logging(paths.logs_dir, settings.log_level, settings.log_file)

    from scrapyfy.models import Company, Post

    session_factory = build_session_factory(settings)

    with session_scope(session_factory) as session:
        # Build query
        query = (
            session.query(Company.slug, Post.platform, Post.post_url)
            .join(Company, Post.company_id == Company.id)
            .filter(Post.post_url.isnot(None))
        )

        # Apply filters
        if platform:
            query = query.filter(Post.platform == platform)
        if company_slug:
            query = query.filter(Company.slug == company_slug)

        results = query.all()

        if not results:
            typer.echo("No posts found with the specified filters.")
            return

        # Group by platform and company
        grouped = {}
        for company, plt, url in results:
            key = f"{plt.upper()} - {company}"
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(url)

        # Output grouped results
        for key in sorted(grouped.keys()):
            typer.echo(f"\n{key}:")
            for url in grouped[key]:
                typer.echo(url)

    logger.info(
        "Post links listed: platform=%s company=%s results=%d",
        platform,
        company_slug,
        len(results),
    )


@app.command("list-companies")
def list_companies() -> None:
    """List all companies with their slugs."""
    settings = Settings()
    root = Path.cwd()
    paths = Paths(root=root)
    configure_logging(paths.logs_dir, settings.log_level, settings.log_file)

    from scrapyfy.models import Company

    session_factory = build_session_factory(settings)

    with session_scope(session_factory) as session:
        companies = session.query(Company).order_by(Company.name).all()

        if not companies:
            typer.echo("No companies found.")
            return

        typer.echo("\nCompanies:")
        typer.echo("─" * 50)
        for company in companies:
            typer.echo(f"{company.name:<30} | {company.slug}")
        typer.echo("─" * 50)
        typer.echo(f"Total: {len(companies)} companies\n")

    logger.info("Companies listed: count=%d", len(companies))


@app.command("add-company")
def add_company() -> None:
    """Add a new company to targets.yaml with interactive prompts."""
    root = Path.cwd()
    paths = Paths(root=root)

    # Read current targets
    targets_path = paths.config_dir / "targets.yaml"
    with open(targets_path, encoding="utf-8") as f:
        targets_data = yaml.safe_load(f)

    existing_slugs = {c["slug"] for c in targets_data.get("companies", [])}

    # Get company name
    name = typer.prompt("Company name")
    slug = _generate_slug(name)

    # Verify slug doesn't exist
    if slug in existing_slugs:
        typer.echo(f"✗ Error: Company with slug '{slug}' already exists.", err=True)
        raise typer.Exit(1)

    # Confirm slug
    if not typer.confirm(f"Use slug '{slug}'?", default=True):
        custom_slug = typer.prompt("Enter custom slug")
        if custom_slug in existing_slugs:
            typer.echo(f"✗ Error: Company with slug '{custom_slug}' already exists.", err=True)
            raise typer.Exit(1)
        slug = custom_slug

    # Get social media handles (optional)
    handles = {}
    platforms = ["facebook", "instagram", "tiktok", "linkedin", "youtube"]

    typer.echo("\nEnter social media handles (press Enter to skip):")
    for platform in platforms:
        url = typer.prompt(f"  {platform.capitalize()}", default="").strip()
        if url:
            handles[platform] = url

    # Create company entry
    company_entry = {
        "name": name,
        "slug": slug,
    }

    # Only add handles if any were provided
    if handles:
        company_entry["handles"] = handles

    # Add to targets
    if "companies" not in targets_data:
        targets_data["companies"] = []

    targets_data["companies"].append(company_entry)

    # Sort companies by name for consistency
    targets_data["companies"] = sorted(targets_data["companies"], key=lambda x: x["name"].lower())

    # Write back to file
    with open(targets_path, "w", encoding="utf-8") as f:
        yaml.dump(
            targets_data,
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )

    # Show summary
    typer.echo("\n✓ Company registered successfully!\n")
    typer.echo("Summary:")
    typer.echo("─" * 50)
    typer.echo(f"Name:  {name}")
    typer.echo(f"Slug:  {slug}")
    if handles:
        typer.echo("Handles:")
        for platform, url in handles.items():
            typer.echo(f"  • {platform.capitalize()}: {url}")
    else:
        typer.echo("Handles: (none)")
    typer.echo("─" * 50 + "\n")

    logger.info(
        "Company added: name=%s slug=%s handles=%d",
        name,
        slug,
        len(handles),
    )


@app.command("debug-comment-stats")
def debug_comment_stats(platform: str | None = typer.Option(None)) -> None:
    """Debug: Show comment statistics by company and platform."""
    settings = Settings()
    root = Path.cwd()
    paths = Paths(root=root)
    configure_logging(paths.logs_dir, settings.log_level, settings.log_file)

    from sqlalchemy import func

    from scrapyfy.models import Comment, Company, Post

    session_factory = build_session_factory(settings)

    with session_scope(session_factory) as session:
        # Query to get stats
        query = (
            session.query(
                Company.slug,
                Post.platform,
                func.count(Comment.id).label("total_comments"),
                func.count(func.nullif(Comment.comment_url, "")).label("comments_with_url"),
            )
            .join(Post, Comment.post_id == Post.id)
            .join(Company, Post.company_id == Company.id)
            .group_by(Company.slug, Post.platform)
        )

        if platform:
            query = query.filter(Post.platform == platform)

        results = query.all()

        if not results:
            typer.echo("No data found.")
            return

        typer.echo("\nComment Statistics:")
        typer.echo("─" * 70)
        typer.echo(f"{'Company':<25} {'Platform':<15} {'Total':<10} {'With URL':<10}")
        typer.echo("─" * 70)
        for company, plt, total, with_url in results:
            typer.echo(f"{company:<25} {plt:<15} {total:<10} {with_url:<10}")
        typer.echo("─" * 70)

    logger.info("Debug stats shown for platform=%s", platform)


@app.command("export-excel")
def export_excel(
    single_company_slug: str | None = typer.Argument(
        None,
        metavar="COMPANY_SLUG",
        help="Single company slug to export (e.g., caja-arequipa)",
    ),
    platform: str | None = typer.Option(
        None,
        help="Optional platform for a multi-company benchmark export",
    ),
    company_slug: str | None = typer.Option(
        None,
        "--company-slug",
        help="Comma-separated list of company slugs for platform export",
    ),
    output_dir: str = typer.Option(
        ".", help="Directory to save the Excel file (default: current directory)"
    ),
    upload_to_spaces: bool = typer.Option(
        True, help="Upload file to DigitalOcean Spaces (if configured)"
    ),
) -> None:
    """Export either a single-company report or a multi-company platform benchmark workbook."""
    settings = Settings()
    root = Path.cwd()
    paths = Paths(root=root)
    configure_logging(paths.logs_dir, settings.log_level, settings.log_file)

    try:
        service = ExcelReportService(database_url=settings.database_url)

        if platform:
            if platform not in set(PLATFORMS):
                raise typer.BadParameter(
                    f"Invalid platform: {platform}. Allowed: {', '.join(sorted(set(PLATFORMS)))}"
                )
            if not company_slug:
                raise typer.BadParameter(
                    "--company-slug is required when using --platform. "
                    "Example: --company-slug interbank,mibanco"
                )

            selected_companies = _parse_company_slugs(company_slug)
            output_path = service.generate_platform_report(
                platform=platform,
                company_slugs=selected_companies,
                output_dir=output_dir,
            )
        else:
            if not single_company_slug:
                raise typer.BadParameter(
                    "Provide a COMPANY_SLUG for the classic export or use --platform "
                    "with --company-slug for the multi-company export"
                )
            output_path = service.generate_report(single_company_slug, output_dir=output_dir)

        logger.info("Excel report generated: %s", output_path)
        typer.echo(f"✓ Report saved: {output_path}")

        # Upload to Spaces if enabled and requested
        if upload_to_spaces:
            from scrapyfy.spaces_service import SpacesUploadService

            spaces_service = SpacesUploadService(settings)
            if spaces_service.enabled:
                file_path = Path(output_path)
                remote_key = f"exports/{file_path.name}"
                download_url = spaces_service.upload_file(file_path, remote_key)

                if download_url:
                    typer.echo(f"✓ Uploaded to Spaces: {download_url}")
                    logger.info("File uploaded to Spaces: %s", download_url)
                else:
                    typer.echo("✗ Failed to upload to Spaces (check logs for details)")
                    logger.warning("Failed to upload file to Spaces")
            else:
                logger.debug(
                    "Spaces not configured, skipping upload. "
                    "Set DIGITALOCEAN_SPACES_* env vars to enable."
                )
    except ValueError as e:
        logger.error("Export failed: %s", str(e))
        typer.echo(f"✗ Error: {str(e)}", err=True)
        raise typer.Exit(1) from e
    except Exception as e:
        logger.exception("Unexpected error during export")
        typer.echo(f"✗ Unexpected error: {str(e)}", err=True)
        raise typer.Exit(1) from e


if __name__ == "__main__":
    app()
