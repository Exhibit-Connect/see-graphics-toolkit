"""Tests for the client spec-packet builder (tools/generate_spec_packet.py).

The packet is a branded 16in x 9in slide deck mirroring SEE's official 2025
client-presentation deck (cover / who-we-are / info / graphic-placement rendering
/ graphics-to-submit / how-to-build / artwork-guidelines / thank-you). These cover
the deck framing, the dynamic content, and the graceful degradation of the official
brand pages when the local-only assets/brand/ folder is absent."""
import generate_spec_packet as gsp

BASE = {"job": {"name": "Test", "client": "Acme", "show": "IMTS 2026",
                "booth_size": "10' x 20'", "job_number": "123"},
        "settings": {"scale": 0.5, "bleed_per_side_in": 1.0},
        "panels": [{"name": "A", "w": 10, "h": 20, "finish": "fabric", "sided": "single"}]}


def test_packet_is_16x9_slide_deck():
    html = gsp.build_html(dict(BASE))
    assert "size: 16in 9in" in html                          # every page is a 16x9 slide
    assert ("slide-coverreal" in html) or ("slide-cover" in html)  # cover slide present
    assert 'class="slide slide-doc"' in html                 # graphics content slide


def test_cover_shows_client_and_show():
    html = gsp.build_html(dict(BASE))
    assert "Acme" in html                       # client name on the cover pill
    assert "IMTS 2026" in html                  # show name


def test_info_slide_carries_job_number():
    html = gsp.build_html(dict(BASE))
    assert 'class="slide slide-info"' in html
    assert "123" in html                        # job # on the project-info slide


def test_spec_packet_embeds_rendering_when_present():
    html = gsp.build_html(dict(BASE, __rendering_uri="data:image/png;base64,ABC123"))
    assert "Graphic Placement" in html
    assert "data:image/png;base64,ABC123" in html


def test_spec_packet_omits_rendering_slide_when_absent():
    assert "Graphic Placement" not in gsp.build_html(dict(BASE))


def test_3d_render_slide_present_only_when_set():
    html = gsp.build_html(dict(BASE, __rendering_3d_uri="data:image/png;base64,REND3D"))
    assert "Booth Rendering" in html and "data:image/png;base64,REND3D" in html
    assert "Booth Rendering" not in gsp.build_html(dict(BASE))


def test_cover_has_geometric_background():
    svg = gsp.cover_bg_svg()
    assert "<polygon" in svg and "<svg" in svg          # recreated chevron geometry (fallback)
    html = gsp.build_html(dict(BASE))
    # the cover uses SEE's real cover image when the brand assets exist, otherwise the
    # recreated SVG geometric background — either way it is never a plain flat cover
    assert ("slide-coverreal" in html) or ("data:image/svg+xml" in html)


def test_artwork_guidelines_is_native_slide_always():
    # the guidelines page is now laid out natively (not a pasted image), so it renders
    # even without the brand assets, and carries the accepted-format chips + copyright line
    html = gsp.build_html(dict(BASE))
    assert 'class="slide slide-guidelines"' in html
    assert 'class="afmt"' in html                       # Ps / Ai / Id / PDF chips
    assert "Copyright Protected" in html
    assert 'class="slide slide-guide"' not in html      # old pasted-image slide is gone


def test_img_data_uri_missing_or_blank_is_empty():
    assert gsp.img_data_uri("/no/such/file.png") == ""
    assert gsp.img_data_uri("") == ""


def test_rendering_data_uri_missing_is_empty():
    assert gsp.rendering_data_uri("/no/such/file.png") == ""
    assert gsp.rendering_data_uri("") == ""


def test_rendering_data_uri_trims_surrounding_white(tmp_path):
    import base64, io
    from PIL import Image
    im = Image.new("RGB", (400, 300), (255, 255, 255))          # mostly white
    for x in range(150, 250):                                   # a small black block
        for y in range(120, 180):
            im.putpixel((x, y), (0, 0, 0))
    p = tmp_path / "render.png"
    im.save(p)
    uri = gsp.rendering_data_uri(str(p))
    assert uri.startswith("data:image/png;base64,")
    out = Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1])))
    assert out.width < 400 and out.height < 300                 # white margins trimmed away


def test_official_brand_pages_present_or_cleanly_absent():
    import branding
    html = gsp.build_html(dict(BASE))
    # Who We Are and Thank You are official image pages that embed only when the
    # local-only brand assets exist; otherwise the deck must render without them.
    if branding.brand_page_data_uri("thank_you"):
        assert 'class="slide slide-full"' in html    # who-we-are + thank-you image pages
    else:
        assert 'class="slide slide-full"' not in html
