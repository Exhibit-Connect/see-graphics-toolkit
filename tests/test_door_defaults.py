"""P0-14: the Python templates must draw the same door the production .jsx draws.

A booth spec WITHOUT door_standard used to yield a production template WITH the
built-in door (the .jsx falls back to a full door) but a client template silently
WITHOUT it — the client designs over the door cut. `preview_templates.DOOR_DEFAULT`
(single source, mirroring the .jsx fallback) closes that split; unrecognized
door / door_marks-side values now warn on stderr instead of drawing nothing silently.
"""
import os
import re

import client_templates as ct
import preview_templates as pt

SETTINGS = {"bleed_per_side_in": 1.0, "safe_margin_in": 4.0, "scale": 0.5}


def test_door_drawn_from_default_when_no_door_standard():
    panel = {"name": "A", "w": 78.12, "h": 173.32, "door": "left"}
    svg = pt.panel_guides_svg(panel, SETTINGS, {}, 0, 0, 1.0)   # falsy door_standard
    assert pt.C["door"] in svg
    assert svg.count("<circle") == 2                            # handle + lock holes


def test_default_door_holes_at_jsx_positions():
    # px=1, origin (0,0), bleed 1 -> trim bottom y = 1 + 173.32 = 174.32
    panel = {"name": "A", "w": 78.12, "h": 173.32, "door": "left"}
    svg = pt.panel_guides_svg(panel, SETTINGS, None, 0, 0, 1.0)
    assert 'width="39.1" height="95.2"' in svg   # 39.125" x 95.21" door leaf
    assert 'cx="5.3"' in svg                     # holes 4.3125" in from the latch edge
    assert 'cy="136.3" r="1.0"' in svg           # handle: 2.0" dia @ 37.98" from floor
    assert 'cy="132.5" r="0.6"' in svg           # lock: 1.125" dia @ 41.79" from floor


def test_client_template_page_draws_default_door():
    spec = {"settings": SETTINGS,                # NO door_standard in the spec
            "panels": [{"name": "A", "w": 78.12, "h": 173.32, "door": "left",
                        "finish": "fabric", "sided": "single"}]}
    html = ct.panel_page_html(spec["panels"][0], spec, 2, 2)
    assert pt.C["door"] in html
    assert html.count("<circle") == 2


def test_unrecognized_door_value_warns_and_draws_nothing(capsys):
    panel = {"name": "A", "w": 78.12, "h": 173.32, "door": "Left"}   # wrong case
    svg = pt.panel_guides_svg(panel, SETTINGS, None, 0, 0, 1.0)
    assert pt.C["door"] not in svg              # matches the .jsx: exact lowercase only
    err = capsys.readouterr().err
    assert '"A"' in err and '"Left"' in err and "door" in err.lower()


def test_unrecognized_door_mark_side_warns_but_still_marks_opening(capsys):
    panel = {"name": "F", "w": 300, "h": 95.2,
             "door_marks": [{"x": 100, "w": 39.06, "label": "D1", "side": "rigth"}]}
    svg = pt.panel_guides_svg(panel, SETTINGS, None, 0, 0, 1.0)
    assert "D1" in svg and pt.C["door"] in svg   # the opening is still marked
    assert svg.count("<circle") == 0             # but no holes for a bad side
    assert '"rigth"' in capsys.readouterr().err


def test_lowercase_door_values_do_not_warn(capsys):
    pt.panel_guides_svg({"name": "A", "w": 78, "h": 173, "door": "right"},
                        SETTINGS, None, 0, 0, 1.0)
    assert capsys.readouterr().err == ""


def test_door_default_matches_the_jsx_fallback():
    # Drift guard: DOOR_DEFAULT must equal the .jsx's `SPEC.door_standard || {...}`
    # fallback numbers — edit one side alone and this fails.
    jsx_path = os.path.join(os.path.dirname(os.path.abspath(pt.__file__)),
                            "SEE_Wall_Template_Generator.jsx")
    jsx = open(jsx_path, encoding="utf-8").read()
    m = re.search(r"SPEC\.door_standard\)?\s*\|\|\s*\{(.*?)\};", jsx, re.S)
    assert m, "could not find the .jsx DOOR fallback block"
    block = m.group(1)

    def num(key):
        mm = re.search(rf"{key}:\s*([\d.]+)", block)
        assert mm, f"{key} missing from the .jsx fallback"
        return float(mm.group(1))

    d = pt.DOOR_DEFAULT
    assert d["panel_w_in"] == num("panel_w_in")
    assert d["panel_h_in"] == num("panel_h_in")
    assert d["edge_offset_in"] == num("edge_offset_in")
    hm = re.search(r"handle:\s*\{\s*dia_in:\s*([\d.]+),\s*y_from_floor_in:\s*([\d.]+)", block)
    lm = re.search(r"lock:\s*\{\s*dia_in:\s*([\d.]+),\s*y_from_floor_in:\s*([\d.]+)", block)
    assert hm and lm, "handle/lock lines missing from the .jsx fallback"
    assert d["handle"] == {"dia_in": float(hm.group(1)), "y_from_floor_in": float(hm.group(2))}
    assert d["lock"] == {"dia_in": float(lm.group(1)), "y_from_floor_in": float(lm.group(2))}
