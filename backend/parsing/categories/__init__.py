from .base import ReportCategory
from .quarterly_update import QuarterlyTradingUpdate
from .half_year_results import HalfYearResults
from .dividend import DividendAnnouncement
from .security_notification import SecurityNotification
from .corporate_action import CorporateAction
from .leadership_change import LeadershipChange
from .transcript import ExecutiveTranscript

# Order matters: more specific categories are evaluated before broader ones.
CATEGORIES: list[type[ReportCategory]] = [
    QuarterlyTradingUpdate,
    HalfYearResults,
    DividendAnnouncement,
    SecurityNotification,
    CorporateAction,
    LeadershipChange,
    ExecutiveTranscript,
]

__all__ = [
    "ReportCategory",
    "CATEGORIES",
    "QuarterlyTradingUpdate",
    "HalfYearResults",
    "DividendAnnouncement",
    "SecurityNotification",
    "CorporateAction",
    "LeadershipChange",
    "ExecutiveTranscript",
]
