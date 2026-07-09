"""Tests for the shared SEE branding helper in tools/branding.py.

These keep all generated documents (spec sheet, check report, proof) on one
consistent logo + contact block.
"""
import base64

import branding
import make_proof
import proofer


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


# ---- P3-3: make_proof branding is deduped into this module ----------------

def test_make_proof_aliases_branding_logo():
    assert make_proof._logo_data_uri is branding.logo_data_uri


def test_make_proof_brand_constants_come_from_one_source():
    assert make_proof.CONTACT is branding.CONTACT
    assert make_proof.RED == branding.RED
    # verdict badge colors derive from proofer.BADGE (incl. the REVIEW entry)
    assert make_proof.VCOL == {k: proofer.BADGE[k] for k in ("PASS", "REVIEW", "FAIL")}


def test_css_proof_built_from_brand_constants():
    assert branding.RED in make_proof.CSS_PROOF
    assert branding.FONT_STACK in make_proof.CSS_PROOF


def test_decoy_client_logo_in_cwd_is_never_embedded(tmp_path):
    """The old wildcard `*[Ll]ogo*.png` glob over cwd could embed a client's
    own logo file as SEE's brand mark on a client-facing proof. Only the
    canonical assets/see_logo.png names may match now."""
    decoy = b"\x89PNG-DECOY-CLIENT-LOGO-BYTES"
    (tmp_path / "Client_Logo.png").write_bytes(decoy)          # cwd (autouse chdir)
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "Client_Logo.png").write_bytes(decoy)
    branding.logo_data_uri.cache_clear()
    try:
        uri = branding.logo_data_uri()
        assert base64.b64encode(decoy).decode() not in uri
        # the real repo logo (assets/see_logo.png next to tools/) still resolves
        assert uri.startswith("data:image/png;base64,")
    finally:
        branding.logo_data_uri.cache_clear()


def test_missing_logo_yields_wordmark_fallback(tmp_path, monkeypatch):
    """With no see_logo.png in either assets/ location, logo_data_uri returns
    '' (never a near-miss like Client_Logo.png) and the text wordmark fires."""
    fake_tools = tmp_path / "fake" / "tools"
    fake_tools.mkdir(parents=True)
    monkeypatch.setattr(branding, "__file__", str(fake_tools / "branding.py"))
    (tmp_path / "Client_Logo.png").write_bytes(b"decoy")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "Client_Logo.png").write_bytes(b"decoy")
    branding.logo_data_uri.cache_clear()
    try:
        assert branding.logo_data_uri() == ""
        assert "see-wordmark" in branding.header_html("X")
    finally:
        branding.logo_data_uri.cache_clear()
