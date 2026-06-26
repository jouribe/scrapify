from scrapyfy.pipeline import Pipeline


def test_dominant_sentiment_label_positive() -> None:
    metrics = {
        "positive_count": 10,
        "neutral_count": 2,
        "negative_count": 1,
    }
    assert Pipeline._dominant_sentiment_label(metrics) == "POSITIVE"


def test_dominant_sentiment_label_tie_defaults_neutral() -> None:
    metrics = {
        "positive_count": 4,
        "neutral_count": 4,
        "negative_count": 1,
    }
    assert Pipeline._dominant_sentiment_label(metrics) == "NEUTRAL"


def test_post_sentiment_label_no_data() -> None:
    metrics = {
        "valid_comments": 0,
        "positive_count": 0,
        "neutral_count": 0,
        "negative_count": 0,
    }
    assert Pipeline._post_sentiment_label(metrics) == "NO_DATA"
