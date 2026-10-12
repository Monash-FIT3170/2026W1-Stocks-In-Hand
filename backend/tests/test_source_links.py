"""Publisher document links must open without scraper-only request parameters."""

from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from app.services.source_links import artifact_source_url, browser_source_url, TCL_PUBLIC_APP_ID
from scrapers.companies.tcl import TCLScraper

TCL_URL = 'https://yourir.info/api/v5/symbols/tcl.asx/announcements/3A703481/document'


def test_tcl_viewer_adds_public_parameters_for_existing_bare_document_links():
    url = browser_source_url(TCL_URL)
    assert urlsplit(url).path == urlsplit(TCL_URL).path
    assert parse_qs(urlsplit(url).query) == {'appID': [TCLScraper.APP_ID], 'liveness': ['live']}
    assert TCL_PUBLIC_APP_ID == TCLScraper.APP_ID
    assert browser_source_url(url) == url


def test_viewer_preserves_explicit_parameters_and_pdf_fragment():
    url = browser_source_url(TCL_URL + '?appID=existing-id&liveness=archive&extra=value#page=2')
    assert parse_qs(urlsplit(url).query) == {'appID': ['existing-id'], 'liveness': ['archive'], 'extra': ['value']}
    assert urlsplit(url).fragment == 'page=2'


def test_blank_viewer_parameters_are_replaced():
    url = browser_source_url(TCL_URL + '?appID=&liveness=')
    assert parse_qs(urlsplit(url).query) == {'appID': [TCL_PUBLIC_APP_ID], 'liveness': ['live']}


@pytest.mark.parametrize('url', [
    'https://yourir.info/api/v5/symbols/anz.asx/announcements/3A123/document',
    'https://yourir.info.evil.test/api/v5/symbols/tcl.asx/announcements/3A123/document',
    'https://example.test/report.pdf?appID=leave-alone',
    'https://yourir.info/resources/public/report.pdf',
])
def test_parameters_are_not_added_to_other_publisher_paths(url):
    assert browser_source_url(url) == url


def test_source_selection_repairs_legacy_metadata_without_mutating_identity():
    artifact = SimpleNamespace(document_url=None, url='https://www.transurban.com/investor-centre/asx-releases.html', artifact_metadata={'pdf_url': TCL_URL})
    assert artifact_source_url(artifact) == browser_source_url(TCL_URL)
    assert artifact.artifact_metadata['pdf_url'] == TCL_URL
    assert artifact.document_url is None


@pytest.mark.parametrize('url', ['javascript:alert(1)', '//yourir.info/test', 'https://user:password@yourir.info/test', None])
def test_invalid_source_urls_remain_unavailable(url):
    assert browser_source_url(url) is None
