import json
import re

import httpx

from app.core.config import settings

CATEGORY_KEYS = ("revenue", "strategy", "risk", "dividend", "organisational")
PROMPT_VERSION = "gemini-category-v1"
ARTIFACT_SEPARATOR = "\n\n---\n\n"


def _empty_categories() -> dict[str, str]:
    return {key: "" for key in CATEGORY_KEYS}


def _extract_json_text(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def parse_category_response(text: str) -> dict[str, str]:
    data = json.loads(_extract_json_text(text))
    if not isinstance(data, dict):
        raise ValueError("Gemini response must be a JSON object")

    missing = [key for key in CATEGORY_KEYS if key not in data]
    if missing:
        raise ValueError(f"Gemini response missing categories: {', '.join(missing)}")
    extra = [key for key in data if key not in CATEGORY_KEYS]
    if extra:
        raise ValueError(f"Gemini response included unexpected categories: {', '.join(extra)}")

    categories = _empty_categories()
    for key in CATEGORY_KEYS:
        value = data.get(key, "")
        categories[key] = value.strip() if isinstance(value, str) else str(value)
    return categories


def _build_prompt(chunk: str) -> str:
    return f"""
You are analysing scraped ASX announcement artifacts for a financial sentiment workflow.

Sort the evidence into exactly these five categories:
revenue, strategy, risk, dividend, organisational.

Return strict JSON only. Use an empty string when the supplied text has no useful evidence for a category.
Do not include markdown, explanations, or extra keys.

Artifact text:
{chunk}
""".strip()


def categorise_chunk(chunk: str) -> dict[str, str]:
    if not settings.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{settings.GEMINI_MODEL}:generateContent"
    )
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": _build_prompt(chunk)}
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.2,
        },
    }

    response = httpx.post(
        url,
        headers={"x-goog-api-key": settings.GEMINI_API_KEY},
        json=payload,
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()

    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("Gemini response did not include text output") from exc

    return parse_category_response(text)


def _split_artifact_batches(chunk: str, batch_size: int) -> list[str]:
    artifacts = [part.strip() for part in chunk.split(ARTIFACT_SEPARATOR) if part.strip()]
    if not artifacts or batch_size <= 0:
        return [chunk]
    return [
        ARTIFACT_SEPARATOR.join(artifacts[index:index + batch_size])
        for index in range(0, len(artifacts), batch_size)
    ]


def _merge_categories(results: list[dict[str, str]]) -> dict[str, str]:
    merged = _empty_categories()
    for key in CATEGORY_KEYS:
        parts = [result[key] for result in results if result.get(key)]
        merged[key] = "\n\n".join(parts)
    return merged


def categorise_chunk_in_batches(chunk: str, batch_size: int) -> dict[str, str]:
    batches = _split_artifact_batches(chunk, batch_size)
    results = [categorise_chunk(batch) for batch in batches]
    return _merge_categories(results)
