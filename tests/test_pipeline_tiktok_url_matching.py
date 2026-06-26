from scrapyfy.pipeline import Pipeline


def test_extract_parent_post_url_tiktok_variants() -> None:
    payload = {
        "videoWebUrl": "https://www.tiktok.com/@entel_peru/video/7577885621763509521",
    }
    assert (
        Pipeline._extract_parent_post_url(payload)
        == "https://www.tiktok.com/@entel_peru/video/7577885621763509521"
    )


def test_normalize_url_for_matching_removes_query_and_trailing_slash() -> None:
    source = "https://www.tiktok.com/@entel_peru/video/7577885621763509521/?foo=bar#x"
    normalized = Pipeline._normalize_url_for_matching(source)
    assert normalized == "https://www.tiktok.com/@entel_peru/video/7577885621763509521"
