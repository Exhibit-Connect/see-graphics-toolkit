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


def test_multiple_placement_images_each_get_their_own_page():
    html = gsp.build_html(dict(BASE, __rendering_items=[
        {"uri": "data:image/png;base64,PLACE1", "caption": "Conference rooms F-L"},
        {"uri": "data:image/png;base64,PLACE2", "caption": "Display walls A-G"},
    ]))
    assert "data:image/png;base64,PLACE1" in html and "data:image/png;base64,PLACE2" in html
    assert "Graphic Placement" in html and "Graphic Placement (cont.)" in html
    assert "Conference rooms F-L" in html and "Display walls A-G" in html  # per-image captions
    assert html.count('class="slide slide-place"') >= 2


def test_placement_uses_default_caption_when_none_given():
    html = gsp.build_html(dict(BASE, __rendering_items=[
        {"uri": "data:image/png;base64,PLACE1", "caption": None}]))
    assert "Graphics-to-Submit sizes on the following pages" in html


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


def test_plan_graphics_pages_places_every_row_once_in_order():
    costs = [60] * 40                                   # 40 rows, more than one slide holds
    pages = gsp.plan_graphics_pages(costs)
    placed = [i for pg in pages for i in pg["rows"]]
    assert placed == list(range(40))                    # every row once, order preserved
    assert len(pages) > 1                               # actually paginated


def test_plan_graphics_pages_respects_capacity():
    costs = [60] * 40
    pages = gsp.plan_graphics_pages(costs, cap=650, thead=44)
    for pg in pages:
        if len(pg["rows"]) > 1:                         # a lone row may exceed cap (never dropped)
            assert pg["used"] <= 650


def test_plan_graphics_pages_banner_on_first_page_only():
    pages = gsp.plan_graphics_pages([60] * 12, banner_est=300)
    assert pages[0]["banner"] is True
    assert all(not pg["banner"] for pg in pages[1:])


def test_plan_graphics_pages_excluded_gets_placed():
    pages = gsp.plan_graphics_pages([60] * 12, excl_est=200)
    assert sum(1 for pg in pages if pg["excl"]) == 1    # exclusions land on exactly one page


def test_plan_graphics_pages_oversized_lone_row_not_dropped():
    # a single row taller than the whole slide must still be placed (never silently lost)
    pages = gsp.plan_graphics_pages([9999, 60, 60], cap=650)
    placed = [i for pg in pages for i in pg["rows"]]
    assert placed == [0, 1, 2]


def test_all_panels_appear_across_paginated_slides():
    many = dict(BASE)
    many["panels"] = [{"name": f"Panel-{i:02d}", "w": 100, "h": 50, "finish": "fabric",
                       "sided": "single", "needs_confirm": True,
                       "note": "A fairly long note " * 8} for i in range(25)]
    many["pending_inputs"] = ["confirm everything"] * 6
    html = gsp.build_html(many)
    for i in range(25):
        assert f"Panel-{i:02d}" in html                 # no panel is clipped/dropped
    assert html.count('class="slide slide-doc"') >= 2   # table spread over multiple slides
    assert "Graphics to Submit (cont.)" in html         # continuation header present


def test_small_job_stays_single_graphics_slide():
    html = gsp.build_html(dict(BASE))                   # 1 panel
    assert html.count('class="slide slide-doc"') == 1
    assert "Graphics to Submit (cont.)" not in html


def test_official_brand_pages_present_or_cleanly_absent():
    import branding
    html = gsp.build_html(dict(BASE))
    # Who We Are and Thank You are official image pages that embed only when the
    # local-only brand assets exist; otherwise the deck must render without them.
    if branding.brand_page_data_uri("thank_you"):
        assert 'class="slide slide-full"' in html    # who-we-are + thank-you image pages
    else:
        assert 'class="slide slide-full"' not in html
