"""
ETL pipeline: classify → extract → store

Entry point for processing scraped ASX announcements.

Running in Docker: (ensure you are in /spike directory)
    docker compose exec backend python parsing/pipeline.py

"""
import os
import platform
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Make scrapers importable regardless of working directory
_BACKEND_DIR = Path(__file__).parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from groq import Groq
from pypdf import PdfReader

from classifier import ReportCategory, classify
from storage import store
from scrapers.base import Announcement


@dataclass
class ProcessedReport:
    announcement: Announcement
    category: type[ReportCategory] | None
    confidence: float
    method: str  # "rules" or "llm"
    extracted_data: dict = field(default_factory=dict)


def extract_text(local_path: Path) -> str:
    reader = PdfReader(local_path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def process_announcement(announcement: Announcement, groq_client: Groq) -> ProcessedReport:
    text = extract_text(announcement.local_path)
    category, confidence, method = classify(announcement.title, text, groq_client)

    extracted_data = (
        category.get_output(announcement.title, text, groq_client)
        if category is not None
        else {}
    )

    store(announcement, category, extracted_data)

    return ProcessedReport(
        announcement=announcement,
        category=category,
        confidence=confidence,
        method=method,
        extracted_data=extracted_data,
    )


if __name__ == "__main__":
    import pprint
    from datetime import datetime
    import env

    env.load_env()
    client = Groq(api_key=os.environ["GROQ_API_KEY"])

    OUTPUT_DIR = Path(__file__).parents[1 if platform.system() != "Windows" else 2] / "output"

    test_cases = [
        ("ANZ", "2026-02-12_2026_First_Quarter_Trading_Update___Pillar_3_Discussion_Pack.pdf"),
        ("ANZ", "2026-05-01_ANZ_1H_2026_Results_Presentation___Investor_Discussion_Pack.pdf"),
        ("ANZ", "2026-02-24_Update_on_former_CEO_s_legal_action.pdf"),
    ]

    for ticker, filename in test_cases:
        pdf_path = OUTPUT_DIR / ticker / filename
        if not pdf_path.exists():
            print(f"[skip] {filename} — not found")
            continue

        ann = Announcement(
            ticker=ticker,
            title=Path(filename).stem.replace("_", " "),
            date=datetime.now(),
            pdf_url="",
            source_url="",
            local_path=pdf_path,
        )
        report = process_announcement(ann, client)
        category_name = report.category.name if report.category else "UNKNOWN"
        print(f"\n--- {filename} ---")
        print(f"Category:   {category_name}")
        print(f"Confidence: {report.confidence:.2f}  Method: {report.method}")
        pprint.pprint(report.extracted_data, width=100, sort_dicts=False)
