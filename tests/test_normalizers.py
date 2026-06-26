from scrapyfy.normalizers import normalize_comment, normalize_post


def test_normalize_post_basic():
    payload = {
        "id": "abc",
        "url": "https://example.com/post/1",
        "text": "hola",
        "authorUsername": "demo",
        "timestamp": "2025-01-01T00:00:00Z",
        "likesCount": 10,
    }

    normalized = normalize_post("instagram", payload)

    assert normalized["external_id"] == "abc"
    assert normalized["post_url"] == "https://example.com/post/1"
    assert normalized["content"] == "hola"
    assert normalized["author"] == "demo"
    assert normalized["metrics"]["likes"] == 10


def test_normalize_comment_basic():
    payload = {
        "commentId": "c1",
        "commentText": "ok",
        "authorUsername": "user",
        "createdAt": "2025-01-01T00:00:00Z",
    }

    normalized = normalize_comment("facebook", payload)

    assert normalized["external_id"] == "c1"
    assert normalized["content"] == "ok"
    assert normalized["author"] == "user"


def test_normalize_post_supports_unix_timestamp() -> None:
    payload = {
        "id": "fb1",
        "authorUsername": "demo",
        "timestamp": 1763153227,
    }

    normalized = normalize_post("facebook", payload)

    assert normalized["posted_at"] is not None
    assert normalized["posted_at"].year == 2025


def test_normalize_post_supports_linkedin_posted_at_iso() -> None:
    payload = {
        "id": "li1",
        "authorUsername": "demo",
        "postedAtISO": "2026-04-07T00:06:18.940Z",
    }

    normalized = normalize_post("linkedin", payload)

    assert normalized["posted_at"] is not None
    assert normalized["posted_at"].year == 2026


def test_normalize_post_supports_youtube_fields() -> None:
    payload = {
        "videoId": "yt1",
        "url": "https://www.youtube.com/watch?v=yt1",
        "title": "video demo",
        "channelName": "Demo Channel",
        "publishedAt": "2026-05-01T10:00:00Z",
        "viewCount": 1234,
        "likeCount": 77,
        "commentCount": 9,
    }

    normalized = normalize_post("youtube", payload)

    assert normalized["external_id"] == "yt1"
    assert normalized["post_url"] == "https://www.youtube.com/watch?v=yt1"
    assert normalized["content"] == "video demo"
    assert normalized["author"] == "Demo Channel"
    assert normalized["metrics"]["views"] == 1234
    assert normalized["metrics"]["likes"] == 77
