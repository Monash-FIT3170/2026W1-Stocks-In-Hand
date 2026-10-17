"""CBA: the YourIR feed behind CommBank's ASX announcements page.

CommBank's widget shows announcements about other issuers too (for example
substantial holdings it lodges), so the feed includes them.
"""

from ..yourir import YOURIR_HOST, YourIRAdapter, YourIRFeed


class CBAAdapter(YourIRAdapter):
    feed = YourIRFeed(
        symbol="cba.asx",
        app_id="e381e7bfa5abbe55",
        referer="https://www.commbank.com.au/",
        page_size=12,
        include_other_issuers=True,
        documents="resource",
        qualified_ids=True,
    )
    hosts = frozenset({"www.commbank.com.au", "commbank.com.au", YOURIR_HOST})
