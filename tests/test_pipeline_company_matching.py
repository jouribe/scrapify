from scrapyfy.config import CompanyHandles, CompanyTarget, Settings, TargetConfig
from scrapyfy.pipeline import Pipeline


class _DummyService:
    pass


def _build_pipeline() -> Pipeline:
    targets = TargetConfig(
        companies=[
            CompanyTarget(
                name="Yape",
                slug="yape",
                handles=CompanyHandles(
                    facebook="https://www.facebook.com/yapeoficial",
                    instagram="https://www.instagram.com/yapeoficial",
                    tiktok="https://www.tiktok.com/@yapeoficial",
                    linkedin="https://www.linkedin.com/company/yape",
                ),
            ),
            CompanyTarget(
                name="BCP",
                slug="bcp",
                handles=CompanyHandles(
                    facebook="https://www.facebook.com/bcp",
                    instagram="https://www.instagram.com/viabcp",
                    tiktok="https://www.tiktok.com/@viabcp",
                    linkedin="https://www.linkedin.com/company/bcp",
                ),
            ),
            CompanyTarget(
                name="Delice",
                slug="delice",
                handles=CompanyHandles(
                    youtube="https://www.youtube.com/@DelicePeru",
                ),
            ),
        ]
    )
    return Pipeline(
        settings=Settings(database_url="postgresql+psycopg://x:y@localhost:5432/z"),
        targets=targets,
        service=_DummyService(),
        session_factory=None,  # type: ignore[arg-type]
    )


def test_detect_company_slug_for_platform_by_input_url() -> None:
    pipeline = _build_pipeline()
    item = {"inputUrl": "https://www.tiktok.com/@yapeoficial/video/123"}
    assert pipeline._detect_company_slug_for_platform(item, "tiktok") == "yape"


def test_detect_company_slug_for_platform_by_username() -> None:
    pipeline = _build_pipeline()
    item = {"ownerUsername": "viabcp"}
    assert pipeline._detect_company_slug_for_platform(item, "instagram") == "bcp"


def test_detect_company_slug_for_platform_by_youtube_channel_url() -> None:
    pipeline = _build_pipeline()
    item = {"channelUrl": "https://www.youtube.com/@DelicePeru/videos"}
    assert pipeline._detect_company_slug_for_platform(item, "youtube") == "delice"


def test_normalize_linkedin_slug_handles_none_and_blank() -> None:
    pipeline = _build_pipeline()
    assert pipeline._normalize_linkedin_slug(None) is None
    assert pipeline._normalize_linkedin_slug("   ") is None
