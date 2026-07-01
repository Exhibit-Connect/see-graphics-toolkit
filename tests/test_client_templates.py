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
