"""Transurban (TCL): the YourIR feed behind its ASX releases page."""

from ..yourir import YOURIR_HOST, YourIRAdapter, YourIRFeed


class TCLAdapter(YourIRAdapter):
    feed = YourIRFeed(
        symbol="tcl.asx",
        app_id="a50955429d255a58",
        referer="https://www.transurban.com/",
        page_size=15,
        include_other_issuers=False,
        documents="api",
    )
    hosts = frozenset({"www.transurban.com", "transurban.com", YOURIR_HOST})
