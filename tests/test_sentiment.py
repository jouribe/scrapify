"""Tests for sentiment analysis service and aggregation functions."""

from scrapyfy.sentiment_service import (
    SentimentService,
    aggregate_sentiment_metrics,
    aggregate_weighted_sentiment,
)


def test_is_emoji_only():
    """Test emoji-only content detection."""
    service = SentimentService(
        model_id="cardiffnlp/twitter-xlm-roberta-base-sentiment",
        device="cpu",
        load_model=False,
    )

    # Emoji-only comments
    assert service._is_emoji_only("😀😍❤️") is True
    assert service._is_emoji_only("😀 😍 ❤️") is True
    assert service._is_emoji_only("😀😍❤️😊") is True

    # Mixed with text (not emoji-only)
    assert service._is_emoji_only("😀 hello") is False
    assert service._is_emoji_only("hello 😀") is False
    assert service._is_emoji_only("h😀llo") is False

    # Not emoji
    assert service._is_emoji_only("hello world") is False
    assert service._is_emoji_only("") is False


def test_emoji_sentiment_analysis():
    """Test emoji sentiment scoring."""
    service = SentimentService(
        model_id="cardiffnlp/twitter-xlm-roberta-base-sentiment",
        device="cpu",
        load_model=False,
    )

    # Positive emojis
    result = service._analyze_emoji_sentiment("😀😍❤️👏")
    assert result is not None
    assert result["label"] == "positive"
    assert result["counts"]["pos"] == 4

    # Negative emojis
    result = service._analyze_emoji_sentiment("😡😢😠💔")
    assert result is not None
    assert result["label"] == "negative"
    assert result["counts"]["neg"] == 4

    # Mixed
    result = service._analyze_emoji_sentiment("😀😀😡")
    assert result is not None
    assert result["label"] in ("positive", "neutral")
    assert result["counts"]["pos"] == 2
    assert result["counts"]["neg"] == 1


def test_aggregate_sentiment_metrics_empty():
    """Test aggregation with no comments."""
    result = aggregate_sentiment_metrics([], 0)

    assert result["valid_comments"] == 0
    assert result["positive_count"] == 0
    assert result["negative_count"] == 0
    assert result["positive_pct"] == 0.0


def test_aggregate_sentiment_metrics_basic():
    """Test aggregation with analyzed comments."""
    comments = [
        {"sentiment_label": "positive", "sentiment_score": 0.95, "sentiment_source": "hf_model"},
        {"sentiment_label": "positive", "sentiment_score": 0.87, "sentiment_source": "hf_model"},
        {"sentiment_label": "neutral", "sentiment_score": 0.5, "sentiment_source": "hf_model"},
        {"sentiment_label": "negative", "sentiment_score": 0.92, "sentiment_source": "emoji_rule"},
    ]

    result = aggregate_sentiment_metrics(comments, 4)

    assert result["valid_comments"] == 4
    assert result["positive_count"] == 2
    assert result["neutral_count"] == 1
    assert result["negative_count"] == 1
    assert result["positive_pct"] == 50.0
    assert result["neutral_pct"] == 25.0
    assert result["negative_pct"] == 25.0
    assert result["text_count"] == 3
    assert result["emoji_only_count"] == 1


def test_weighted_aggregation_single_post():
    """Test weighted aggregation with one post."""
    post_metrics = [
        {
            "valid_comments": 10,
            "positive_count": 6,
            "neutral_count": 2,
            "negative_count": 2,
            "avg_confidence": 0.85,
        }
    ]

    result = aggregate_weighted_sentiment(post_metrics)

    assert result["valid_comments"] == 10
    assert result["positive_count"] == 6
    assert result["negative_count"] == 2
    assert result["post_count"] == 1


def test_weighted_aggregation_multiple_posts():
    """Test weighted aggregation across multiple posts."""
    post_metrics = [
        {
            "valid_comments": 10,
            "positive_count": 8,
            "neutral_count": 1,
            "negative_count": 1,
            "avg_confidence": 0.90,
        },
        {
            "valid_comments": 20,
            "positive_count": 10,
            "neutral_count": 5,
            "negative_count": 5,
            "avg_confidence": 0.75,
        },
    ]

    result = aggregate_weighted_sentiment(post_metrics)

    # Total valid: 30
    # Total positive: 18, pct = 18/30*100 = 60%
    # Total negative: 6, pct = 6/30*100 = 20%
    assert result["valid_comments"] == 30
    assert result["positive_count"] == 18
    assert result["negative_count"] == 6
    assert result["positive_pct"] == 60.0
    assert result["negative_pct"] == 20.0
    assert result["post_count"] == 2


def test_weighted_aggregation_net_sentiment():
    """Test net sentiment calculation."""
    post_metrics = [
        {
            "valid_comments": 10,
            "positive_count": 7,
            "neutral_count": 2,
            "negative_count": 1,
            "avg_confidence": 0.85,
        }
    ]

    result = aggregate_weighted_sentiment(post_metrics)

    # net_sentiment = (7 - 1) / 10 = 0.6
    assert result["net_sentiment"] == 0.6


def test_weighted_aggregation_zero_valid_keeps_post_count():
    """When posts have no valid comments, total posts should still be represented."""
    post_metrics = [
        {"valid_comments": 0, "positive_count": 0, "neutral_count": 0, "negative_count": 0},
        {"valid_comments": 0, "positive_count": 0, "neutral_count": 0, "negative_count": 0},
    ]

    result = aggregate_weighted_sentiment(post_metrics)

    assert result["valid_comments"] == 0
    assert result["post_count"] == 2
