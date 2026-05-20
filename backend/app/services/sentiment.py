from functools import lru_cache
from typing import Any, Mapping

from transformers import pipeline

from app.core.config import settings

MAX_CHUNK_CHARS = 1600
OVERLAP_WORDS = 40
SENTIMENT_LABELS = ("positive", "neutral", "negative")
LABEL_ALIASES = {"label_0": "positive", "label_1": "negative", "label_2": "neutral"}


def _normalise_label(label: str):
    cleaned = (label or "").strip().lower()
    if cleaned in SENTIMENT_LABELS:
        return cleaned
    return LABEL_ALIASES.get(cleaned, cleaned)


def _split_text(text: str):
    words = text.split()
    if not words:
        return []

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for word in words:
        separator_len = 1 if current else 0
        next_len = current_len + separator_len + len(word)

        if current and next_len > MAX_CHUNK_CHARS:
            chunks.append(" ".join(current))
            current = current[-OVERLAP_WORDS:] if OVERLAP_WORDS > 0 else []
            current_len = len(" ".join(current))
            separator_len = 1 if current else 0

        current.append(word)
        current_len += separator_len + len(word)

    if current:
        chunks.append(" ".join(current))

    return chunks


@lru_cache(maxsize=1)
def get_finbert_pipeline():
    try:
        return pipeline("text-classification", model=settings.FINBERT_MODEL)
    except Exception as exc:
        raise RuntimeError(f"FinBERT model could not be loaded from {settings.FINBERT_MODEL}") from exc


def model_name():
    return settings.FINBERT_MODEL


def _empty_result():
    distribution = {"positive": 0.0, "neutral": 0.0, "negative": 0.0}
    return {
        "sentiment_label": "neutral",
        "label": "neutral",
        "score": 0.0,
        "confidence_score": 0.0,
        "distribution": distribution,
        "model_used": model_name(),
        "chunks_used": 0,
        "chunks_analyzed": 0,
    }


def _normalise_pipeline_output(raw_output: Any):
    if isinstance(raw_output, dict):
        return [[raw_output]]
    if not isinstance(raw_output, list) or not raw_output:
        return []
    if isinstance(raw_output[0], dict):
        return [raw_output]
    return raw_output


def analyse_text(text: str):
    cleaned = (text or "").strip()
    if not cleaned:
        return _empty_result()

    chunks = _split_text(cleaned)
    if not chunks:
        return _empty_result()

    label_scores = {label: 0.0 for label in SENTIMENT_LABELS}
    classifier = get_finbert_pipeline()

    raw_output = classifier(chunks, truncation=True, max_length=512, return_all_scores=True)
    prediction_groups = _normalise_pipeline_output(raw_output)

    for chunk, predictions in zip(chunks, prediction_groups):
        weight = max(len(chunk), 1)
        for prediction in predictions:
            label = _normalise_label(str(prediction.get("label", "")))
            if label in label_scores:
                label_scores[label] += float(prediction.get("score", 0.0)) * weight

    total = sum(label_scores.values())
    if total <= 0:
        return _empty_result()

    distribution = {
        label: round(score / total, 4)
        for label, score in label_scores.items()
    }
    sentiment_label = max(distribution, key=lambda label: distribution[label])
    confidence = distribution[sentiment_label]

    return {
        "sentiment_label": sentiment_label,
        "label": sentiment_label,
        "score": confidence,
        "confidence_score": confidence,
        "distribution": distribution,
        "model_used": model_name(),
        "chunks_used": len(chunks),
        "chunks_analyzed": len(chunks),
    }


def analyse_categories(categories: Mapping[str, str | None],):
    results: dict[str, dict[str, Any]] = {}

    for category, summary in categories.items():
        text = (summary or "").strip()
        sentiment = analyse_text(text)
        results[category] = {"summary": text, **sentiment}

    return results
