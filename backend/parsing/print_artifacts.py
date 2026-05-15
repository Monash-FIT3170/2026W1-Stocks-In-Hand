"""
Database inspection CLI for artifacts/reports.

Run in Docker (from project root):
    docker compose exec backend python parsing/print_artifacts.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from app.database.connection import SessionLocal
from app.models.artifact import Artifact


def _print_artifact(a: Artifact, show_extracted: bool = True) -> None:
    meta = a.artifact_metadata or {}
    category = meta.get("category", "-")
    print(f"  [{a.scraped_at:%Y-%m-%d %H:%M}]  {a.title}")
    print(f"    type={a.artifact_type}  category={category}")
    if show_extracted:
        extracted = meta.get("extracted_data", {})
        for k, v in extracted.items():
            print(f"      {k}: {v}")
    print()


def view_all_artifacts(db) -> None:
    rows = db.query(Artifact).order_by(Artifact.scraped_at).all()
    print(f"\n{len(rows)} artifact(s) total\n")
    for a in rows:
        _print_artifact(a, show_extracted=False)


def view_all_reports(db) -> None:
    rows = (
        db.query(Artifact)
        .filter(Artifact.artifact_type == "asx_announcement")
        .order_by(Artifact.scraped_at)
        .all()
    )
    print(f"\n{len(rows)} report(s)\n")
    for a in rows:
        _print_artifact(a)


def view_unknown_reports(db) -> None:
    rows = (
        db.query(Artifact)
        .filter(Artifact.artifact_type == "asx_announcement")
        .filter(Artifact.artifact_metadata["category"].astext == "UNKNOWN")
        .order_by(Artifact.scraped_at)
        .all()
    )
    print(f"\n{len(rows)} UNKNOWN report(s)\n")
    for a in rows:
        _print_artifact(a, show_extracted=False)


def view_classified_reports(db) -> None:
    rows = (
        db.query(Artifact)
        .filter(Artifact.artifact_type == "asx_announcement")
        .filter(Artifact.artifact_metadata["category"].astext != "UNKNOWN")
        .order_by(Artifact.scraped_at)
        .all()
    )
    print(f"\n{len(rows)} classified report(s)\n")
    for a in rows:
        _print_artifact(a)


def drop_reports(db) -> None:
    count = db.query(Artifact).filter(Artifact.artifact_type == "asx_announcement").count()
    confirm = input(f"  Delete {count} report(s)? [y/N] ").strip().lower()
    if confirm == "y":
        db.query(Artifact).filter(Artifact.artifact_type == "asx_announcement").delete()
        db.commit()
        print(f"  Deleted {count} report(s).")
    else:
        print("  Cancelled.")


def drop_all_artifacts(db) -> None:
    count = db.query(Artifact).count()
    confirm = input(f"  Delete ALL {count} artifact(s)? [y/N] ").strip().lower()
    if confirm == "y":
        db.query(Artifact).delete()
        db.commit()
        print(f"  Deleted {count} artifact(s).")
    else:
        print("  Cancelled.")


MENU = [
    ("View all artifacts",                    view_all_artifacts),
    ("View all reports (asx_announcement)",   view_all_reports),
    ("View reports with UNKNOWN category",    view_unknown_reports),
    ("View reports with known category",      view_classified_reports),
    ("Drop all reports",                      drop_reports),
    ("Drop ALL artifacts",                    drop_all_artifacts),
]


def main() -> None:
    db = SessionLocal()
    try:
        while True:
            print("\n--- DB Inspector ---")
            for i, (label, _) in enumerate(MENU, 1):
                print(f"  {i}. {label}")
            print("  Q. Quit")

            choice = input("\nSelect: ").strip().upper()
            if choice == "Q":
                break
            if choice.isdigit() and 1 <= int(choice) <= len(MENU):
                MENU[int(choice) - 1][1](db)
            else:
                print("  Invalid choice.")
    finally:
        db.close()


main()
