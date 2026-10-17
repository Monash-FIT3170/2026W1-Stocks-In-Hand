"""ANZ: the YourIR feed behind ANZ's ASX announcements page."""

from ..yourir import YOURIR_HOST, YourIRAdapter, YourIRFeed


class ANZAdapter(YourIRAdapter):
    feed = YourIRFeed(
        symbol="anz.asx",
        app_id="4d216b570d08af30",
        referer="https://www.anz.com/",
        page_size=20,
        include_other_issuers=False,
        documents="resource",
    )
    hosts = frozenset(
        {"www.anz.com", "anz.com", "www.anz.com.au", "anz.com.au", YOURIR_HOST}
    )
