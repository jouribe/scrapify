"""DigitalOcean Spaces upload service."""

from __future__ import annotations

from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from scrapyfy.config import Settings
from scrapyfy.logging_config import get_logger

logger = get_logger(__name__)


class SpacesUploadService:
    """Handle file uploads to DigitalOcean Spaces."""

    def __init__(self, settings: Settings):
        """Initialize Spaces client."""
        self.settings = settings
        self.enabled = bool(
            settings.digitalocean_spaces_key
            and settings.digitalocean_spaces_secret
            and settings.digitalocean_spaces_name
        )

        if self.enabled:
            endpoint_url = settings.digitalocean_spaces_endpoint or (
                f"https://{settings.digitalocean_spaces_region}.digitaloceanspaces.com"
            )
            self.client = boto3.client(
                "s3",
                region_name=settings.digitalocean_spaces_region,
                endpoint_url=endpoint_url,
                aws_access_key_id=settings.digitalocean_spaces_key,
                aws_secret_access_key=settings.digitalocean_spaces_secret,
            )
        else:
            self.client = None

    def upload_file(self, file_path: Path, remote_key: str | None = None) -> str | None:
        """Upload file to Spaces and return the public URL.

        Args:
            file_path: Local file path to upload
            remote_key: Remote object key (default: just filename)

        Returns:
            Public URL of the uploaded file, or None if Spaces is not configured
        """
        if not self.enabled:
            logger.debug("Spaces not configured, skipping upload")
            return None

        if not file_path.exists():
            logger.error("File not found: %s", file_path)
            return None

        if remote_key is None:
            remote_key = file_path.name

        try:
            # Upload file
            self.client.upload_file(
                str(file_path),
                self.settings.digitalocean_spaces_name,
                remote_key,
                ExtraArgs={"ACL": "public-read"},
            )
            logger.info("File uploaded to Spaces: %s", remote_key)

            # Build public URL
            region = self.settings.digitalocean_spaces_region
            space_name = self.settings.digitalocean_spaces_name
            public_url = f"https://{space_name}.{region}.digitaloceanspaces.com/{remote_key}"

            return public_url

        except ClientError as e:
            logger.error("Failed to upload to Spaces: %s", str(e))
            return None
        except Exception as e:
            logger.error("Unexpected error uploading to Spaces: %s", str(e))
            return None
