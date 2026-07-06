"""Tests for the shared SEE branding helper in tools/branding.py.

These keep all generated documents (spec sheet, check report, proof) on one
consistent logo + contact block.
"""
import branding


def test_contact_names_company_and_url():
    assert "Southeast Exhibits" in branding.CONTACT
    assert "SouthEastExhibit.com" in branding.CONTACT


def test_logo_data_uri_is_png_or_empty():
    uri = branding.logo_data_uri()
    assert uri == "" or uri.startswith("data:image/png;base64,")


def test_header_html_carries_pill_and_contact():
    h = branding.header_html("Graphic Submission Spec Packet")
    assert "Graphic Submission Spec Packet" in h
    assert "see-brandhead" in h
    assert "SouthEastExhibit.com" in h


def test_header_embeds_logo_when_available():
    # the repo ships assets/see_logo.png, so a real run should embed an <img>;
    # with no logo on disk it must fall back to the text wordmark.
    if branding.logo_data_uri():
        assert "<img" in branding.header_html("X")
    else:
        assert "see-wordmark" in branding.header_html("X")


def test_brand_red_is_official_2025_value():
    # sampled from the official 2025 brand sources (presentation + artwork guidelines)
    assert branding.RED == "#E31D3D"


def test_font_stack_leads_with_helvetica_neue():
    assert branding.FONT_STACK.startswith("'Helvetica Neue'")


def test_artwork_guidelines_uri_is_png_or_empty():
    # assets/brand/ is local-only (gitignored); helper must degrade to '' without it
    uri = branding.artwork_guidelines_data_uri()
    assert uri == "" or uri.startswith("data:image/png;base64,")
