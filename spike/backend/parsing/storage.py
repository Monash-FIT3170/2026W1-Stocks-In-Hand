from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scrapers.base import Announcement
    from classifier import ReportCategory


def store(
    announcement: "Announcement",
    category: "type[ReportCategory] | None",
    extracted_data: dict,
) -> None:
    # TODO: implement database storage based on report category
    pass
