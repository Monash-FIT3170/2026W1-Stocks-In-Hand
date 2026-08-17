import json
import re
import time

import httpx

from app.core.config import settings

CATEGORY_KEYS = ("revenue", "strategy", "risk", "dividend", "organisational")
PROMPT_VERSION = "groq-category-v1"
SUMMARY_PROMPT_VERSION = "groq-announcement-summary-v1"
SUMMARY_KEYS = ("summary", "about", "changed", "matters")
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
        raise ValueError("Groq response must be a JSON object")

    missing = [key for key in CATEGORY_KEYS if key not in data]
    if missing:
        raise ValueError(f"Groq response missing categories: {', '.join(missing)}")
    extra = [key for key in data if key not in CATEGORY_KEYS]
    if extra:
        raise ValueError(f"Groq response included unexpected categories: {', '.join(extra)}")

    categories = _empty_categories()
    for key in CATEGORY_KEYS:
        value = data.get(key, "")
        categories[key] = value.strip() if isinstance(value, str) else str(value)
    return categories


def parse_summary_response(text: str) -> dict[str, str]:
    data = json.loads(_extract_json_text(text))
    if not isinstance(data, dict):
        raise ValueError("Groq summary response must be a JSON object")

    missing = [key for key in SUMMARY_KEYS if key not in data]
    if missing:
        raise ValueError(f"Groq summary response missing keys: {', '.join(missing)}")

    summary = {}
    for key in SUMMARY_KEYS:
        value = data.get(key, "")
        summary[key] = value.strip() if isinstance(value, str) else str(value)
    return summary


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


def _build_summary_prompt(
    *,
    title: str,
    category: str,
    extracted_data: dict,
    raw_text: str,
) -> str:
    extracted_json = json.dumps(extracted_data or {}, default=str, indent=2)
    text = raw_text[:18000]
    return f"""
You are summarising an official ASX announcement for retail investors.

Use only the supplied announcement text and extracted fields. Do not invent facts.
Write in clear, plain English. Avoid hype.

Return strict JSON only with exactly these keys:
summary: a concise 2-3 sentence summary.
about: one sentence explaining what the announcement is about.
changed: one sentence explaining what changed, or "No material change identified." if unclear.
matters: one sentence explaining why it may matter to investors.

Title:
{title}

Detected category:
{category}

Extracted fields:
{extracted_json}

Announcement text:
{text}
""".strip()


def _call_groq(prompt: str) -> str:
    if not settings.GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not configured")
    url = "https://api.groq.com/openai/v1/chat/completions"
    payload = {
        "model": settings.GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    for attempt in range(5):
        response = httpx.post(
            url,
            headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
            json=payload,
            timeout=60,
        )
        if response.status_code == 429:
            wait = int(response.headers.get("retry-after", min(2 ** attempt * 5, 60)))
            print(f"[GROQ] Rate limited, retrying in {wait}s (attempt {attempt + 1}/5)")
            time.sleep(wait)
            continue
        response.raise_for_status()
        data = response.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("Groq response did not include text output") from exc
    raise RuntimeError("Groq rate limit exceeded after 5 retries")


def active_model_name() -> str:
    if settings.GROQ_API_KEY:
        return settings.GROQ_MODEL
    return "groq-not-configured"


def _call_llm(prompt: str) -> str:
    """Use Groq for LLM work; do not fall back to Gemini."""
    if settings.GROQ_API_KEY:
        return _call_groq(prompt)
    raise RuntimeError("GROQ_API_KEY is not configured")


def categorise_chunk(chunk: str) -> dict[str, str]:
    return parse_category_response(_call_llm(_build_prompt(chunk)))


def summarise_announcement(
    *,
    title: str,
    category: str,
    extracted_data: dict,
    raw_text: str,
) -> dict[str, str]:
    return parse_summary_response(
        _call_llm(
            _build_summary_prompt(
                title=title,
                category=category,
                extracted_data=extracted_data,
                raw_text=raw_text,
            )
        )
    )


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
