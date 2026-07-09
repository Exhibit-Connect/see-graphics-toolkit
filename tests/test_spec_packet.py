"""Tests for the client spec-packet builder (tools/generate_spec_packet.py).

The packet is a branded 16in x 9in slide deck mirroring SEE's official 2025
client-presentation deck (cover / who-we-are / info / graphic-placement rendering
/ graphics-to-submit / how-to-build / artwork-guidelines / thank-you). These cover
the deck framing, the dynamic content, and the graceful degradation of the official
brand pages when the local-only assets/brand/ folder is absent."""
import re

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


# ---- P0-13: pagination must not silently clip zone-heavy panel rows ----

def test_row_est_px_counts_visible_and_material_lines():
    base = gsp.row_est_px("", False)
    assert gsp.row_est_px("", False, vis_lines=4) == 18 + 4 * 19    # zones + door dominate
    assert gsp.row_est_px("", False, vis_lines=4) > base
    assert gsp.row_est_px("", False, mat_lines=2) == 18 + 2 * 19    # interior_finish line


def test_planned_pages_stay_under_derated_cap():
    # the confirmed bug shape: 12 panels x 3 zones + interior finish estimated
    # 488px but rendered ~884px on a 696px body -> ~3 rows clipped
    costs = [gsp.row_est_px("", False, vis_lines=3, mat_lines=2)] * 12
    pages = gsp.plan_graphics_pages(costs, banner_est=120)
    assert len(pages) > 1                                           # actually paginated now
    for pg in pages:
        assert pg["used"] <= gsp.GFX_CAP_PX * 0.9                   # every page under the derated cap
    assert [i for pg in pages for i in pg["rows"]] == list(range(12))


def test_first_row_overflowing_banner_page_starts_page_two():
    # a big banner nearly fills page 1: the first row must not be forced onto it
    pages = gsp.plan_graphics_pages([200], banner_est=500)
    assert pages[0]["banner"] is True and pages[0]["rows"] == []
    assert pages[1]["rows"] == [0]


def test_excluded_list_respects_the_cap():
    # exclusions must not overflow a nearly-full last page — they get their own page
    pages = gsp.plan_graphics_pages([500], excl_est=200)
    assert pages[-1]["excl"] is True and pages[-1]["rows"] == []
    assert sum(1 for pg in pages if pg["excl"]) == 1


def test_zone_heavy_booth_keeps_every_panel_exactly_once():
    many = dict(BASE)
    many["panels"] = [{"name": f"ZP{i:02d}", "w": 100, "h": 50, "finish": "fabric",
                       "interior_finish": "white PVC", "sided": "single",
                       "zones": [{"x": 0, "y": 0, "w": 10, "h": 10, "kind": "live"},
                                 {"x": 0, "y": 20, "w": 10, "h": 10, "kind": "keepclear", "label": "shelf"},
                                 {"x": 0, "y": 40, "w": 10, "h": 10, "kind": "keepclear", "label": "tv"}]}
                      for i in range(12)]
    html = gsp.build_html(many)
    # count in markup only: base64 image payloads (brand assets, logo) can
    # contain any 4-char run, so data: URIs are stripped before counting
    markup = re.sub(r"data:[^\"']+", "", html)
    for i in range(12):
        assert markup.count(f"ZP{i:02d}") == 1                      # each panel once — never clipped/duplicated
    assert html.count('class="slide slide-doc"') >= 2               # split across slides


# ---- P0-12: settings wired into the deck; live draft flag; scaled bleed text ----

def test_how_to_build_slide_present_with_settings():
    html = gsp.build_html(dict(BASE))
    assert "How to Build" in html
    assert 'class="slide slide-doc slide-howto"' in html
    assert '<ul class="specs">' in html
    assert "Printer marks" in html                      # a specs bullet actually rendered


def test_non_default_color_mode_reaches_the_packet():
    spec = dict(BASE, settings={"scale": 0.5, "bleed_per_side_in": 1.0, "color_mode": "RGB-backlit"})
    assert "RGB-backlit" in gsp.build_html(spec)


def test_non_default_fonts_setting_reaches_the_packet():
    spec = dict(BASE, settings={"scale": 0.5, "bleed_per_side_in": 1.0, "fonts": "embed all fonts"})
    assert "embed all fonts" in gsp.build_html(spec)


def test_half_scale_bleed_wording_gives_scaled_per_side():
    html = gsp.build_html(dict(BASE))                   # scale 0.5, bleed 1.0
    assert "0.5″ per side" in html                      # the ½-scale instruction
    # the old wording told everyone to add the FULL-scale bleed with no caveat
    assert "2″ bleed</b> to the overall width" not in html
    assert "add 1″ on each side" not in html


def test_full_scale_bleed_wording_stays_unscaled():
    spec = dict(BASE, settings={"scale": 1, "bleed_per_side_in": 1.0})
    html = gsp.build_html(spec)
    assert "1″ bleed</b> per side" in html
    assert "0.5″ per side" not in html


def test_draft_ribbon_on_tbd_finish_only_spec():
    spec = dict(BASE, panels=[{"name": "A", "w": 10, "h": 20, "finish": "TBD", "sided": "single"}])
    html = gsp.build_html(spec)
    assert "DRAFT — NOT FOR CLIENT" in html             # visible cover ribbon
    assert "not for client distribution" in html        # disclaimer note


def test_no_draft_ribbon_on_clean_spec():
    assert "DRAFT — NOT FOR CLIENT" not in gsp.build_html(dict(BASE))


def test_final_flag_suppresses_ribbon_in_html():
    spec = dict(BASE, panels=[{"name": "A", "w": 10, "h": 20, "finish": "TBD", "sided": "single"}])
    assert "DRAFT — NOT FOR CLIENT" not in gsp.build_html(spec, final=True)


def test_draft_reasons_lists_all_three():
    spec = dict(BASE, panels=[{"name": "A", "w": 10, "h": 20, "finish": "TBD", "needs_confirm": True}],
                pending_inputs=["confirm door"])
    rs = gsp.draft_reasons(spec)
    assert any("TBD" in r for r in rs)
    assert any("pending" in r for r in rs)
    assert any("unverified" in r for r in rs)
    assert gsp.draft_reasons(dict(BASE)) == []


def _write_spec(tmp_path, spec, name="booth_spec_test.json"):
    import json
    p = tmp_path / name
    p.write_text(json.dumps(spec))
    return p


def test_main_suffixes_draft_output_for_tbd_spec(tmp_path, monkeypatch, capsys):
    import sys
    spec = dict(BASE, panels=[{"name": "A", "w": 10, "h": 20, "finish": "TBD", "sided": "single"}])
    p = _write_spec(tmp_path, spec)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(gsp.render, "html_to_pdf", lambda *a, **k: False)
    monkeypatch.setattr(sys, "argv", ["generate_spec_packet.py", str(p)])
    gsp.main()
    out = capsys.readouterr().out
    assert (tmp_path / "test_Spec_Packet_DRAFT.html").exists()   # filename says DRAFT
    assert not (tmp_path / "test_Spec_Packet.html").exists()
    assert "DRAFT packet" in out and "TBD finishes" in out       # warning lists why


def test_main_final_refuses_while_unverified(tmp_path, monkeypatch, capsys):
    import sys
    import pytest
    spec = dict(BASE, panels=[{"name": "A", "w": 10, "h": 20, "finish": "fabric",
                               "sided": "single", "needs_confirm": True}])
    p = _write_spec(tmp_path, spec)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(gsp.render, "html_to_pdf", lambda *a, **k: False)
    monkeypatch.setattr(sys, "argv", ["generate_spec_packet.py", str(p), "--final"])
    with pytest.raises(SystemExit) as e:
        gsp.main()
    assert e.value.code == 1                                     # nonzero exit
    assert "REFUSED" in capsys.readouterr().out
    assert not list(tmp_path.glob("*_Spec_Packet*.html"))        # nothing was written


def test_main_final_overrides_draft_when_verified(tmp_path, monkeypatch, capsys):
    import sys
    spec = dict(BASE, panels=[{"name": "A", "w": 10, "h": 20, "finish": "TBD", "sided": "single"}])
    p = _write_spec(tmp_path, spec)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(gsp.render, "html_to_pdf", lambda *a, **k: False)
    monkeypatch.setattr(sys, "argv", ["generate_spec_packet.py", str(p), "--final"])
    gsp.main()
    assert (tmp_path / "test_Spec_Packet.html").exists()         # no _DRAFT suffix
    assert "DRAFT — NOT FOR CLIENT" not in (tmp_path / "test_Spec_Packet.html").read_text(encoding="utf-8")


def test_official_brand_pages_present_or_cleanly_absent():
    import branding
    html = gsp.build_html(dict(BASE))
    # Who We Are and Thank You are official image pages that embed only when the
    # local-only brand assets exist; otherwise the deck must render without them.
    if branding.brand_page_data_uri("thank_you"):
        assert 'class="slide slide-full"' in html    # who-we-are + thank-you image pages
    else:
        assert 'class="slide slide-full"' not in html
