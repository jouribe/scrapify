from __future__ import annotations

import re
from typing import Any

from scrapyfy.logging_config import get_logger

logger = get_logger(__name__)

# Emoji sentiment mapping for emoji-only comments
POSITIVE_EMOJIS = {
    "😀",
    "😃",
    "😄",
    "😁",
    "😍",
    "🥰",
    "😘",
    "😊",
    "🙂",
    "☺️",
    "❤️",
    "🧡",
    "💛",
    "💚",
    "💙",
    "🎉",
    "🎊",
    "👏",
    "🙌",
    "✌️",
    "👍",
    "💪",
    "🚀",
    "⭐",
    "✨",
}

NEGATIVE_EMOJIS = {
    "😡",
    "😠",
    "🤬",
    "😢",
    "😭",
    "😤",
    "😞",
    "😔",
    "😕",
    "😖",
    "💔",
    "😱",
    "😨",
    "😰",
    "😳",
    "👎",
    "❌",
    "💀",
    "🔥",
}

NEUTRAL_EMOJIS = {
    "😐",
    "😑",
    "😒",
    "🤔",
    "😶",
    "🤐",
    "💭",
    "🤷",
    "👀",
}


class SentimentService:
    """Service for sentiment analysis using HF models and emoji fallback."""

    def __init__(
        self,
        model_id: str,
        device: str = "cpu",
        batch_size: int = 32,
        load_model: bool = True,
    ) -> None:
        self.model_id = model_id
        self.device = device
        self.batch_size = batch_size
        self.pipeline = None
        if load_model:
            self._load_model()

    def _load_model(self) -> None:
        try:
            from transformers import pipeline

            logger.info(
                "Loading Hugging Face sentiment model: model_id=%s device=%s",
                self.model_id,
                self.device,
            )
            self.pipeline = pipeline(
                "sentiment-analysis",
                model=self.model_id,
                device=0 if self.device == "cuda" else -1,
                use_fast=False,
                truncation=True,
                max_length=512,
            )
            logger.info("Sentiment model loaded successfully")
        except Exception as error:
            logger.exception("Failed to load sentiment model: %s", error)
            raise

    def analyze_comments(
        self, comments: list[dict[str, Any]]
    ) -> list[tuple[dict[str, Any], str | None]]:
        """
        Analyze a batch of comments for sentiment.

        Returns list of (comment, source) tuples where source is 'hf_model' or 'emoji_rule'.
        """
        results: list[tuple[dict[str, Any], str | None]] = []

        for comment in comments:
            content = comment.get("content", "").strip()
            if not content:
                continue

            # Check if it's emoji-only
            if self._is_emoji_only(content):
                enriched = dict(comment)
                enriched["sentiment_source"] = "emoji_rule"
                result = self._analyze_emoji_sentiment(content)
                if result:
                    enriched["sentiment_label"] = result["label"]
                    enriched["sentiment_score"] = result["score"]
                    results.append((enriched, "emoji_rule"))
            else:
                # Use HF model
                enriched = dict(comment)
                enriched["sentiment_source"] = "hf_model"
                result = self._analyze_text_sentiment(content)
                if result:
                    enriched["sentiment_label"] = result["label"]
                    enriched["sentiment_score"] = result["score"]
                    results.append((enriched, "hf_model"))

        return results

    def _is_emoji_only(self, text: str) -> bool:
        """Check if text contains only emojis, spaces, and punctuation."""
        if not text.strip():
            return False

        normalized = text
        for emoji in POSITIVE_EMOJIS | NEGATIVE_EMOJIS | NEUTRAL_EMOJIS:
            normalized = normalized.replace(emoji, "")

        # Remove emojis and common characters.
        cleaned = re.sub(
            r"[\U0001F600-\U0001F64F]|[\U0001F300-\U0001F5FF]|"
            r"[\U0001F680-\U0001F6FF]|[\U0001F1E0-\U0001F1FF]|"
            r"[\U00002500-\U00002BEF]|[\u2600-\u2B55]|[\u200d]|"
            r"[\u200c]|[\uFE0F]|[\s\.\!\?\,\-]",
            "",
            normalized,
            flags=re.UNICODE,
        )
        return len(cleaned) == 0

    def _analyze_emoji_sentiment(self, text: str) -> dict[str, Any] | None:
        """Analyze sentiment from emoji content using heuristic."""
        pos_count = sum(text.count(emoji) for emoji in POSITIVE_EMOJIS)
        neg_count = sum(text.count(emoji) for emoji in NEGATIVE_EMOJIS)
        neu_count = sum(text.count(emoji) for emoji in NEUTRAL_EMOJIS)

        total = pos_count + neg_count + neu_count
        if total == 0:
            return None

        net = (pos_count - neg_count) / total

        if net > 0.2:
            label = "positive"
        elif net < -0.2:
            label = "negative"
        else:
            label = "neutral"

        return {
            "label": label,
            "score": abs(net),
            "counts": {"pos": pos_count, "neg": neg_count, "neu": neu_count},
        }

    def _analyze_text_sentiment(self, text: str) -> dict[str, Any] | None:
        """Analyze sentiment using HF model."""
        if not self.pipeline:
            return None

        try:
            result = self.pipeline(text)
            if result and len(result) > 0:
                item = result[0]
                label = item["label"].lower()
                score = float(item["score"])

                # Normalize label from model output (some models use LABEL_0, LABEL_1, etc)
                if label.startswith("label_"):
                    # cardiffnlp model: LABEL_0=negative, LABEL_1=neutral, LABEL_2=positive
                    label_map = {"label_0": "negative", "label_1": "neutral", "label_2": "positive"}
                    label = label_map.get(label, label)

                return {"label": label, "score": score}
        except Exception as error:
            logger.warning("Sentiment analysis failed for text: %s", error)
            return None

        return None


def aggregate_sentiment_metrics(
    comments_with_sentiment: list[dict[str, Any]], total_valid_comments: int
) -> dict[str, Any]:
    """
    Aggregate sentiment metrics from analyzed comments.

    Calculates counts, percentages, net sentiment, and confidence per class.
    """
    if not comments_with_sentiment or total_valid_comments == 0:
        return {
            "valid_comments": 0,
            "positive_count": 0,
            "neutral_count": 0,
            "negative_count": 0,
            "positive_pct": 0.0,
            "neutral_pct": 0.0,
            "negative_pct": 0.0,
            "net_sentiment": 0.0,
            "avg_confidence": 0.0,
            "emoji_only_count": 0,
            "text_count": 0,
        }

    pos_count = sum(1 for c in comments_with_sentiment if c.get("sentiment_label") == "positive")
    neu_count = sum(1 for c in comments_with_sentiment if c.get("sentiment_label") == "neutral")
    neg_count = sum(
        1 for c in comments_with_sentiment if c.get("sentiment_label") == "negative"
    )

    total_analyzed = len(comments_with_sentiment)

    net_sentiment = (pos_count - neg_count) / total_analyzed if total_analyzed > 0 else 0.0
    avg_confidence = (
        sum(float(c.get("sentiment_score", 0)) for c in comments_with_sentiment)
        / total_analyzed
        if total_analyzed > 0
        else 0.0
    )

    emoji_count = sum(
        1 for c in comments_with_sentiment if c.get("sentiment_source") == "emoji_rule"
    )
    text_count = sum(
        1 for c in comments_with_sentiment if c.get("sentiment_source") == "hf_model"
    )

    return {
        "valid_comments": total_valid_comments,
        "positive_count": pos_count,
        "neutral_count": neu_count,
        "negative_count": neg_count,
        "positive_pct": round((pos_count / total_analyzed * 100), 2) if total_analyzed > 0 else 0.0,
        "neutral_pct": round((neu_count / total_analyzed * 100), 2) if total_analyzed > 0 else 0.0,
        "negative_pct": round((neg_count / total_analyzed * 100), 2) if total_analyzed > 0 else 0.0,
        "net_sentiment": round(net_sentiment, 3),
        "avg_confidence": round(avg_confidence, 3),
        "emoji_only_count": emoji_count,
        "text_count": text_count,
    }


def aggregate_weighted_sentiment(
    post_metrics: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Calculate weighted average sentiment across posts.

    Weight = number of valid_comments in each post.
    """
    if not post_metrics:
        return {
            "valid_comments": 0,
            "positive_count": 0,
            "neutral_count": 0,
            "negative_count": 0,
            "positive_pct": 0.0,
            "neutral_pct": 0.0,
            "negative_pct": 0.0,
            "net_sentiment": 0.0,
            "avg_confidence": 0.0,
            "post_count": 0,
        }

    total_valid = sum(m.get("valid_comments", 0) for m in post_metrics)
    if total_valid == 0:
        return {
            "valid_comments": 0,
            "positive_count": 0,
            "neutral_count": 0,
            "negative_count": 0,
            "positive_pct": 0.0,
            "neutral_pct": 0.0,
            "negative_pct": 0.0,
            "net_sentiment": 0.0,
            "avg_confidence": 0.0,
            "post_count": len(post_metrics),
        }

    # Weighted aggregation
    weighted_pos = sum(m.get("positive_count", 0) for m in post_metrics)
    weighted_neu = sum(m.get("neutral_count", 0) for m in post_metrics)
    weighted_neg = sum(m.get("negative_count", 0) for m in post_metrics)

    total_analyzed = weighted_pos + weighted_neu + weighted_neg

    net_sentiment = (
        (weighted_pos - weighted_neg) / total_analyzed if total_analyzed > 0 else 0.0
    )
    avg_confidence = (
        sum(
            m.get("avg_confidence", 0) * m.get("valid_comments", 0) for m in post_metrics
        )
        / total_valid
        if total_valid > 0
        else 0.0
    )

    return {
        "valid_comments": total_valid,
        "positive_count": weighted_pos,
        "neutral_count": weighted_neu,
        "negative_count": weighted_neg,
        "positive_pct": round((weighted_pos / total_analyzed * 100), 2)
        if total_analyzed > 0
        else 0.0,
        "neutral_pct": round((weighted_neu / total_analyzed * 100), 2)
        if total_analyzed > 0
        else 0.0,
        "negative_pct": round((weighted_neg / total_analyzed * 100), 2)
        if total_analyzed > 0
        else 0.0,
        "net_sentiment": round(net_sentiment, 3),
        "avg_confidence": round(avg_confidence, 3),
        "post_count": len(post_metrics),
    }
