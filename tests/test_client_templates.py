"""Tests for the client-template helpers.

Covers the shared per-panel guide geometry (preview_templates.panel_guides_svg)
and client_templates' pure helpers (oversized_panels, fit_px, caption_rows).
All operate on plain dicts — no Chrome, qlmanage, or files.
"""
import client_templates as ct
import preview_templates as pt

SETTINGS = {"bleed_per_side_in": 1.0, "safe_margin_in": 4.0, "scale": 0.5}
DOOR = {"panel_w_in": 39.125, "panel_h_in": 95.21, "edge_offset_in": 4.3125,
        "handle": {"dia_in": 2.0, "y_from_floor_in": 37.98},
        "lock": {"dia_in": 1.125, "y_from_floor_in": 41.79}}


def test_panel_guides_svg_draws_zones_and_door_holes():
    panel = {"name": "A", "w": 78.12, "h": 173.32, "door": "left",
             "zones": [{"x": 0, "y": 95.2, "w": 78.12, "h": 39.06, "kind": "live"},
                       {"x": 0, "y": 0, "w": 78.12, "h": 95.2, "kind": "keepclear"}]}
    svg = pt.panel_guides_svg(panel, SETTINGS, DOOR, 0, 0, 2.3)
    assert pt.C["bleed"] in svg and pt.C["trim"] in svg
    assert pt.C["live"] in svg and pt.C["keep"] in svg     # both zone kinds drawn
    assert pt.C["door"] in svg
    assert svg.count("<circle") == 2                       # handle + lock holes


def test_panel_guides_svg_safe_area_present_then_omitted():
    big = pt.panel_guides_svg({"name": "B", "w": 78.12, "h": 173.32}, SETTINGS, {}, 0, 0, 2.3)
    assert pt.C["safe"] in big                             # 78×173 leaves room for a 4" safe inset
    tiny = pt.panel_guides_svg({"name": "C", "w": 5, "h": 5}, SETTINGS, {}, 0, 0, 2.3)
    assert pt.C["safe"] not in tiny                        # 5" panel can't hold a 4"/side inset


def test_oversized_panels_flags_only_the_giant():
    spec = {"settings": SETTINGS, "panels": [
        {"name": "Wall", "w": 78.12, "h": 173.32},
        {"name": "Hanging Sign", "w": 603.0, "h": 48.0},   # (603+2)*0.5 = 302.5 > 226
    ]}
    names = [p["name"] for p in ct.oversized_panels(spec)]
    assert names == ["Hanging Sign"]


def test_fit_px_keeps_bleed_box_within_the_draw_area():
    panel = {"name": "Wide", "w": 603.0, "h": 48.0}
    px = ct.fit_px(panel, SETTINGS, max_w=860, max_h=470)
    bleed = SETTINGS["bleed_per_side_in"]
    assert (panel["w"] + 2 * bleed) * px <= 860 + 0.01
    assert (panel["h"] + 2 * bleed) * px <= 470 + 0.01


def test_build_svg_widens_for_long_panel_labels():
    # a narrow panel with a long NAME draws wider than its box; the SVG canvas
    # must grow so the label doesn't clip off the right edge (Uptool regression)
    import re

    def svg_width(name):
        spec = {"settings": {"bleed_per_side_in": 1.0, "safe_margin_in": 4.0},
                "panels": [{"name": name, "w": 20, "h": 37.5}]}
        svg, _ = pt.build_svg(spec)
        return float(re.search(r'width="(\d+(?:\.\d+)?)"', svg).group(1))

    assert svg_width("Counter_Side_Left_Extra_Long") > svg_width("X")


def test_caption_rows_carry_trim_and_bleed_sizes():
    rows = dict(ct.caption_rows({"name": "F1", "w": 78.12, "h": 134.26,
                                 "finish": "Fabric", "sided": "single"}, SETTINGS))
    assert rows["Finished (trim) size"] == '78.12" W × 134.26" H'
    assert rows["File size WITH bleed"] == '80.12" W × 136.26" H'   # +1" each side
    assert rows["Material"] == "Fabric"
    assert rows["Sides"] == "Single-sided"


def test_scale_pct_phrasing():
    assert ct.scale_pct(0.5) == "built at ½ scale (print @200%)"
    assert ct.scale_pct(1) == "full scale"


def test_caption_rows_include_half_scale_build_size():
    # SEE builds at ½ scale then prints 200% — the exact build size must be shown
    rows = ct.caption_rows({"name": "Conf Room - F", "w": 588.15, "h": 95.2}, SETTINGS)
    build = [v for k, v in rows if k.startswith("Build size")]
    assert build, "expected a ½-scale build-size row"
    assert '294.075" × 47.6" trim' in build[0]                 # 588.15/2 × 95.2/2
    assert '295.075" × 48.6" with bleed' in build[0]           # (w+2)/2 × (h+2)/2


def test_caption_rows_omit_build_scale_at_full_scale():
    rows = dict(ct.caption_rows({"name": "X", "w": 40, "h": 40}, {"scale": 1, "bleed_per_side_in": 1.0}))
    assert not any(k.startswith("Build size") for k in rows)


def test_is_continuous_flag():
    assert ct.is_continuous({"oversize_mode": "continuous"})
    assert not ct.is_continuous({"oversize_mode": "tile"})
    assert not ct.is_continuous({})


def test_panel_guides_svg_draws_marked_doors():
    panel = {"name": "F", "w": 588.15, "h": 95.2,
             "door_marks": [{"x": 119.43, "w": 39.06, "label": "Door Cut 1"},
                            {"x": 197.55, "w": 39.06, "label": "Door Cut 2"}]}
    svg = pt.panel_guides_svg(panel, SETTINGS, DOOR, 0, 0, 1.4)
    assert "Door Cut 1" in svg and "Door Cut 2" in svg
    assert pt.C["door"] in svg
    assert svg.count("<circle") == 0            # no side given -> mark the opening only


def test_panel_guides_svg_marked_door_with_side_adds_holes():
    panel = {"name": "F", "w": 300, "h": 95.2,
             "door_marks": [{"x": 100, "w": 39.06, "label": "D1", "side": "left"}]}
    svg = pt.panel_guides_svg(panel, SETTINGS, DOOR, 0, 0, 1.4)
    assert svg.count("<circle") == 2            # handle + lock holes on the latch edge


def test_continuous_oversize_draws_template_not_seam_notice():
    spec = {"settings": SETTINGS, "door_standard": DOOR,
            "panels": [{"name": "F", "w": 588.15, "h": 95.2, "oversize_mode": "continuous",
                        "door_marks": [{"x": 119.43, "w": 39.06, "label": "Door Cut 1"}]}]}
    html = ct.panel_page_html(spec["panels"][0], spec, 2, 2, oversized=True)
    assert "One continuous graphic" in html            # the no-seams banner
    assert "printed in sections and seamed" not in html  # NOT the tile/seam notice
    assert "<svg" in html and "Door Cut 1" in html     # the drawn template with doors
    assert "Door openings are marked" in html          # door clause present when doors exist


def test_cover_tags_every_continuous_wall_one_piece():
    # the cover "one piece" tag follows the continuous flag, not the artboard-oversized
    # check — so a continuous wall that happens to fit an artboard is still marked
    spec = {"settings": SETTINGS, "panels": [
        {"name": "M", "w": 588.15, "h": 95.2, "oversize_mode": "continuous"},  # oversized + continuous
        {"name": "N", "w": 314.73, "h": 95.2, "oversize_mode": "continuous"},  # continuous, fits artboard
        {"name": "Seamed", "w": 603.0, "h": 48.0},                             # oversized, NOT continuous
        {"name": "Plain", "w": 78.0, "h": 40.0},                               # normal single panel
    ]}
    html = ct._cover_page(spec, spec["panels"], 5)   # P1-10: settings-driven predicate
    assert html.count("one piece") == 2      # both continuous walls, not just the oversized one
    assert "tile/seam" in html               # the oversized non-continuous piece


def test_continuous_banner_omits_door_clause_when_no_doors():
    # a wide wall printed in one piece but WITHOUT doors shouldn't claim doors are marked
    spec = {"settings": SETTINGS, "panels": [{"name": "N", "w": 314.73, "h": 95.2,
                                              "oversize_mode": "continuous"}]}
    html = ct.panel_page_html(spec["panels"][0], spec, 2, 2, oversized=False)
    assert "One continuous graphic" in html
    assert "Door openings are marked" not in html


ALUVISION = {"panel_w_in": 33.1875, "panel_h_in": 91.0625, "edge_offset_in": 1.81,
             "handle": {"dia_in": 2.0, "y_from_floor_in": 37.98},
             "lock": {"dia_in": 1.125, "y_from_floor_in": 41.79}}


def _door_leaf_svg():
    import re
    px = 2.0
    panel = {"name": "N", "w": 314.73, "h": 95.2,
             "door_marks": [{"x": 0, "w": 39.06, "label": "D", "side": "right", "leaf": True}]}
    svg = pt.panel_guides_svg(panel, SETTINGS, ALUVISION, 0, 0, px)
    rects = re.findall(r'<rect x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)" '
                       r'fill="none" stroke="' + re.escape(pt.C["door"]), svg)
    return svg, rects, px


def test_door_mark_leaf_draws_panel_with_centered_inner_door():
    # a door PANEL (bay) with leaf:true draws the panel opening (full trim height) AND
    # the actual door leaf from door_standard, centered inside it and bottom-anchored
    svg, rects, px = _door_leaf_svg()
    assert len(rects) == 2                                       # panel + leaf
    panel_r = max(rects, key=lambda r: float(r[2]))             # wider  = the 39" panel
    leaf_r  = min(rects, key=lambda r: float(r[2]))             # narrower = the leaf
    assert abs(float(panel_r[2]) - 39.06 * px) < 0.2
    assert abs(float(leaf_r[2]) - 33.1875 * px) < 0.2
    assert float(leaf_r[3]) < float(panel_r[3])                # leaf shorter than the full panel
    panel_cx = float(panel_r[0]) + float(panel_r[2]) / 2       # leaf centered in the panel
    leaf_cx  = float(leaf_r[0]) + float(leaf_r[2]) / 2
    assert abs(panel_cx - leaf_cx) < 0.5
    assert svg.count("<circle") == 2                            # handle + lock, on the leaf


def test_door_mark_leaf_holes_ride_the_leaf_edge():
    # with leaf:true the handle/lock holes sit on the LEAF's latch edge (inset by the
    # frame reveal), NOT on the wider panel edge
    import re
    svg, _, px = _door_leaf_svg()
    cx = float(re.search(r'<circle cx="([\d.]+)"', svg).group(1))
    tlx = SETTINGS["bleed_per_side_in"] * px                    # trim/panel left
    leaf_x = tlx + (39.06 - 33.1875) / 2 * px                   # centered leaf's left edge
    expected = leaf_x + 33.1875 * px - 1.81 * px               # side right -> leaf right edge - offset
    assert abs(cx - expected) < 0.5
    assert cx < (tlx + 39.06 * px) - 1.81 * px - 1             # inset from the panel edge


def test_door_mark_without_leaf_is_single_opening():
    # backward compatible: no `leaf` -> one full-height opening at dm.w, holes on its edge
    import re
    px = 2.0
    panel = {"name": "M", "w": 588.15, "h": 95.2,
             "door_marks": [{"x": 100, "w": 39.06, "label": "D", "side": "left"}]}
    svg = pt.panel_guides_svg(panel, SETTINGS, ALUVISION, 0, 0, px)
    rects = re.findall(r'<rect x="[\d.]+" y="[\d.]+" width="([\d.]+)" height="[\d.]+" '
                       r'fill="none" stroke="' + re.escape(pt.C["door"]), svg)
    assert len(rects) == 1                                      # just the opening, no inner leaf
    assert abs(float(rects[0]) - 39.06 * px) < 0.2


def test_resolve_door_standard_by_template():
    # a `door_template` name resolves (case-insensitively) to the built-in profile
    alu = pt.resolve_door_standard({"door_template": "aluvision"})
    assert alu["panel_w_in"] == 33.1875 and alu["panel_h_in"] == 91.0625
    assert alu["edge_offset_in"] == 1.81 and alu["handle_style"] == "holes"
    bm = pt.resolve_door_standard({"door_template": "BMatrix"})
    assert bm["panel_w_in"] == 32.9375 and bm["handle_style"] == "slot"


def test_resolve_door_standard_unknown_raises():
    import pytest
    with pytest.raises(ValueError):
        pt.resolve_door_standard({"door_template": "acme-doors"})


def test_resolve_door_standard_fallbacks():
    inline = {"panel_w_in": 40, "panel_h_in": 90}
    assert pt.resolve_door_standard({"door_standard": inline}) is inline   # inline wins when no template
    assert pt.resolve_door_standard({}) is pt.DOOR_DEFAULT                 # neither -> built-in default


def test_slot_handle_draws_leaf_without_holes():
    # a BMatrix (slot) door draws the panel + leaf but NO round holes (slot geometry TBD)
    import re
    px = 2.0
    bm = pt.DOOR_PROFILES["bmatrix"]
    panel = {"name": "V", "w": 314.73, "h": 95.2,
             "door_marks": [{"x": 0, "w": 39.06, "label": "D", "side": "right", "leaf": True}]}
    svg = pt.panel_guides_svg(panel, SETTINGS, bm, 0, 0, px)
    assert svg.count("<circle") == 0                                       # slot handle not drawn yet
    rects = re.findall(r'<rect [^>]*stroke="' + re.escape(pt.C["door"]), svg)
    assert len(rects) == 2                                                 # panel + leaf still drawn


# ---------- P1-10: per-panel output safety, honest PDF failures, identity-safe oversized ----------
import json
import os
import sys

import pytest

import render


def test_is_oversized_predicate():
    assert ct.is_oversized({"name": "Giant", "w": 603.0, "h": 48.0}, SETTINGS)
    assert not ct.is_oversized({"name": "Wall", "w": 78.12, "h": 173.32}, SETTINGS)


def test_duplicate_names_only_the_oversized_one_gets_seam_notice():
    # two panels named "Counter": only the genuinely oversized OBJECT is
    # tile/seam - the old name-keyed set misclassified both
    spec = {"settings": SETTINGS, "panels": [
        {"name": "Counter", "w": 603.0, "h": 48.0},   # oversized
        {"name": "Counter", "w": 40.0, "h": 40.0},    # normal
    ]}
    html = ct.build_templates_html(spec)
    assert html.count("printed in sections and seamed") == 1
    assert html.count("tile/seam") == 1               # cover tag too


def _write_spec(tmp_path, panels):
    spec = {"job": {"name": "T"}, "settings": SETTINGS, "panels": panels}
    p = tmp_path / "booth_spec_t.json"
    p.write_text(json.dumps(spec))
    return str(p)


def test_per_panel_stem_collision_gets_index(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sp = _write_spec(tmp_path, [{"name": "Wall-1", "w": 10, "h": 20},
                                {"name": "Wall 1", "w": 30, "h": 40}])
    rendered = []

    def fake_pdf(hp, pp):
        rendered.append(os.path.basename(pp))
        open(pp, "w", encoding="utf-8").write("pdf")
        return True

    monkeypatch.setattr(ct.render, "html_to_pdf", fake_pdf)
    monkeypatch.setattr(sys, "argv", ["client_templates.py", sp, "--per-panel"])
    ct.main()
    per_panel = [r for r in rendered if r.endswith("_template.pdf")]
    assert len(per_panel) == len(set(per_panel)) == 2    # distinct outputs
    assert any("_2_template.pdf" in r for r in per_panel)  # index disambiguates


def test_per_panel_failed_render_keeps_html_and_names_panel(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    sp = _write_spec(tmp_path, [{"name": "Good", "w": 10, "h": 20},
                                {"name": "Bad", "w": 30, "h": 40}])

    def fake_pdf(hp, pp):
        if "Bad" in hp:
            return False
        open(pp, "w", encoding="utf-8").write("pdf")
        return True

    monkeypatch.setattr(ct.render, "html_to_pdf", fake_pdf)
    # Chrome "absent": the failure is the legitimate fallback -> exit 0
    monkeypatch.setenv("SEE_CHROME", str(tmp_path / "no_chrome"))
    monkeypatch.setattr(sys, "argv", ["client_templates.py", sp, "--per-panel"])
    ct.main()                                            # no SystemExit
    out = capsys.readouterr().out
    assert "per-panel FAILED (HTML kept for manual print): Bad" in out
    assert "per-panel PDFs: 1 of 2" in out
    kept = [f for f in os.listdir(tmp_path) if f.endswith("_template.html")]
    assert kept == ["t_Bad_template.html"]               # failed panel's HTML kept


def test_render_failure_with_chrome_present_exits_1(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    sp = _write_spec(tmp_path, [{"name": "A", "w": 10, "h": 20}])
    monkeypatch.setattr(ct.render, "html_to_pdf", lambda *a, **k: False)
    monkeypatch.setenv("SEE_CHROME", sys.executable)           # "Chrome" exists
    monkeypatch.setattr(sys, "argv", ["client_templates.py", sp])
    with pytest.raises(SystemExit) as ei:
        ct.main()
    assert ei.value.code == 1
    assert "PDF render FAILED" in capsys.readouterr().out


def test_chrome_absent_fallback_still_exit_0(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    sp = _write_spec(tmp_path, [{"name": "A", "w": 10, "h": 20}])
    monkeypatch.setattr(ct.render, "html_to_pdf", lambda *a, **k: False)
    monkeypatch.setenv("SEE_CHROME", str(tmp_path / "no_chrome"))
    monkeypatch.setattr(sys, "argv", ["client_templates.py", sp])
    ct.main()                                            # no SystemExit
    assert "PDF step skipped (Chrome not installed)" in capsys.readouterr().out


# ---------- P3-6: exact scale percentage + seam-notice wording ----------
def test_scale_pct_exact_percentage():
    # 0.75 scale prints at 133.33%, not a rounded '@133%' a vendor would take literally
    assert ct.scale_pct(0.75) == "built at ¾ scale (print @133.33%)"
    assert ct.scale_pct(0.5) == "built at ½ scale (print @200%)"   # integral stays whole
    assert ct.scale_pct(0.4) == "built at 0.4× scale (print @250%)"


def test_seam_notice_formats_dims_and_names_the_caption_row():
    spec = {"settings": SETTINGS, "panels": [{"name": "Seamed", "w": 603.0, "h": 48.0}]}
    html = ct.panel_page_html(spec["panels"][0], spec, 1, 1, oversized=True)
    assert '(603" × 48")' in html                 # :g — no trailing '.0'
    assert "File size WITH bleed" in html         # names the exact caption row
    assert "shown at right" in html


def test_seam_notice_omits_parenthetical_when_dims_missing():
    spec = {"settings": SETTINGS, "panels": [{"name": "S"}]}
    html = ct.panel_page_html(spec["panels"][0], spec, 1, 1, oversized=True)
    assert "too large for one template." in html  # no '(None" × None")'
    assert "None" not in html
