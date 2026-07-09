"""P2-7: drift guards tying the Illustrator generator (.jsx) to the Python side.

The .jsx runs only inside Illustrator, so nothing executes it in CI — these
tests regex-extract its constants and pin them to the Python modules that must
agree with it. Edit either side alone and the matching test fails.

Companion coverage that already exists elsewhere:
- tests/test_door_defaults.py pins preview_templates.DOOR_DEFAULT to the .jsx
  door fallback (P0-14);
- tests/test_jsx_guards.py holds the node --check syntax gate and the
  P0-15 behavior-presence guards + the CLAUDE.md manual-checklist guard.
"""
import json
import os
import re

import client_templates as ct
import intake

JSX_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "tools", "SEE_Wall_Template_Generator.jsx")


def _jsx():
    with open(JSX_PATH, encoding="utf-8") as f:
        return f.read()


def test_max_artboard_matches_client_templates_max_build():
    """A panel the .jsx can fit on one artboard must never be told to
    tile/seam by the client templates (and vice versa)."""
    m = re.search(r"MAX_AB_PT\s*=\s*(\d+(?:\.\d+)?)\s*\*\s*72", _jsx())
    assert m, "MAX_AB_PT constant not found in the .jsx"
    assert float(m.group(1)) == ct.MAX_BUILD_IN


def test_jsx_setting_defaults_match_intake_settings():
    """The defaults the .jsx applies when a spec omits a setting must equal the
    defaults intake.py writes into every draft spec — otherwise a drafted booth
    and a sparse hand-authored booth build DIFFERENT templates."""
    src = _jsx()

    def jsx_default(key):
        m = re.search(rf"\(ST\.{key} != null\)\s*\?\s*ST\.{key}\s*:\s*([\d.]+)", src)
        assert m, f"default for settings.{key} not found in the .jsx"
        return float(m.group(1))

    assert jsx_default("scale") == intake.SETTINGS["scale"]
    assert jsx_default("bleed_per_side_in") == intake.SETTINGS["bleed_per_side_in"]
    assert jsx_default("safe_margin_in") == intake.SETTINGS["safe_margin_in"]


def test_jsx_assigns_a_cmyk_guide_color_to_all_six_key_roles():
    """Invariant 3 on the Illustrator side: every guide role in the color key
    (cyan=bleed, black=trim, magenta=safe, orange=keep-clear, green=live,
    red=door) keeps its own CMYK color assignment in the .jsx."""
    src = _jsx()
    assignments = dict(re.findall(r"var (C_[A-Z]+)\s*=\s*cmyk\(([^)]*)\);", src))
    for role in ("C_BLEED", "C_TRIM", "C_SAFE", "C_KEEP", "C_LIVE", "C_DOOR"):
        assert role in assignments, f"{role} guide color assignment missing from the .jsx"
    # the six roles must be six DISTINCT colors — two roles sharing a color
    # makes the guides unreadable even if every assignment still exists
    six = [tuple(float(x) for x in assignments[r].split(","))
           for r in ("C_BLEED", "C_TRIM", "C_SAFE", "C_KEEP", "C_LIVE", "C_DOOR")]
    assert len(set(six)) == 6, f"guide roles share a CMYK color: {six}"
    # and each role's color is actually USED to draw (not just defined)
    for role in ("C_BLEED", "C_TRIM", "C_SAFE", "C_KEEP", "C_LIVE", "C_DOOR"):
        assert src.count(role) > 1, f"{role} defined but never used"


def test_jsx_bleed_is_process_cyan_and_safe_area_is_dashed():
    """P3-6 key consistency: the previews draw bleed #00AEEF (process cyan) and
    a DASHED magenta safe line; the production .jsx must draw the same —
    C_BLEED cmyk(100,0,0,0) and a dashed safe-area stroke."""
    src = _jsx()
    m = re.search(r"var C_BLEED\s*=\s*cmyk\(([^)]*)\)", src)
    assert [float(x) for x in m.group(1).split(",")] == [100, 0, 0, 0]
    safe_call = re.search(r"strokeRect\(lSafe,[^;]*\);", src).group(0)
    assert re.search(r",\s*true\s*\)\s*;$", safe_call), "safe-area stroke is not dashed"


# ---------- P0-15: the band layout's cumulative footprint fits the canvas ----


def _jsx_layout_constants(src):
    """Regex-extract the .jsx band-layout constants (all in points except
    GAP_IN, which is in scaled inches)."""
    def const(name):
        m = re.search(rf"var {name}\s*=\s*([\d.]+)\s*\*\s*(?:PT|72)\s*;", src)
        assert m, f"{name} constant not found in the .jsx"
        return float(m.group(1)) * 72.0

    m = re.search(r"var GAP_IN\s*=\s*([\d.]+)\s*;", src)
    assert m, "GAP_IN constant not found in the .jsx"
    return {
        "GAP_IN": float(m.group(1)),
        "MAX_AB_PT": const("MAX_AB_PT"),
        "MAX_ROW_W_PT": const("MAX_ROW_W_PT"),
        "MAX_COL_H_PT": const("MAX_COL_H_PT"),
    }


def _simulate_jsx_band_layout(spec, k):
    """Python replica of the .jsx BUILD loop's artboard placement (rows wrap at
    MAX_ROW_W_PT, column bands start past MAX_COL_H_PT), returning the placed
    artboard rects in points as (left, top, right, bottom) with top<=0."""
    st = spec.get("settings") or {}
    scale = st.get("scale", 0.5)
    bleed = st.get("bleed_per_side_in", 1.0)

    def s_pt(v):                       # scaled inches -> points (sPt in the .jsx)
        return v * scale * 72.0

    gap = s_pt(k["GAP_IN"])
    x_base = 0.0
    band_w = 0.0
    x_cursor = 0.0
    y_top = 0.0
    row_max_h = 0.0
    placed, skipped = [], []

    for p in spec["panels"]:
        sides = 2 if p.get("sided") == "double" else 1
        for _ in range(sides):
            ab_w = s_pt(p["w"]) + 2 * s_pt(bleed)
            ab_h = s_pt(p["h"]) + 2 * s_pt(bleed)
            if ab_w > k["MAX_AB_PT"] or ab_h > k["MAX_AB_PT"]:
                skipped.append(p["name"])
                continue
            if x_cursor > x_base and (x_cursor - x_base + ab_w) > k["MAX_ROW_W_PT"]:
                x_cursor = x_base
                y_top -= row_max_h + gap
                row_max_h = 0.0
            if y_top < 0 and (-y_top + ab_h) > k["MAX_COL_H_PT"]:
                x_base = x_base + band_w + gap
                band_w = 0.0
                x_cursor = x_base
                y_top = 0.0
                row_max_h = 0.0
            placed.append((x_cursor, y_top, x_cursor + ab_w, y_top - ab_h))
            x_cursor += ab_w + gap
            band_w = max(band_w, x_cursor - gap - x_base)
            row_max_h = max(row_max_h, ab_h)
    return placed, skipped


def test_jsx_band_layout_fits_the_example_booth_on_the_canvas():
    """P0-15 geometry gate: replicate the .jsx band algorithm on the shipped
    example booth and require every panel's artboard inside Illustrator's
    16383-pt (~227.5") canvas square. Fails if anyone regresses GAP_IN /
    MAX_ROW_W_PT / MAX_COL_H_PT (or the wrap rules) back past the canvas."""
    canvas_pt = 16383.0
    src = _jsx()
    k = _jsx_layout_constants(src)
    spec_path = os.path.join(os.path.dirname(JSX_PATH), "..",
                             "examples", "1_booth_spec_example.json")
    with open(spec_path, encoding="utf-8") as f:
        spec = json.load(f)

    placed, skipped = _simulate_jsx_band_layout(spec, k)
    assert skipped == [], f"example panels misfiled as oversized: {skipped}"
    assert len(placed) == 18                      # every panel gets an artboard

    union_w = max(r for _, _, r, _ in placed)     # layout starts at x=0
    union_h = max(-b for _, _, _, b in placed)    # ... and y=0, growing down
    assert union_w <= canvas_pt, (
        f"cumulative footprint {union_w / 72:.1f}\" wide exceeds the "
        f"{canvas_pt / 72:.1f}\" Illustrator canvas")
    assert union_h <= canvas_pt, (
        f"cumulative footprint {union_h / 72:.1f}\" tall exceeds the "
        f"{canvas_pt / 72:.1f}\" Illustrator canvas")


def test_jsx_advances_the_cursor_when_an_artboard_fails():
    """A failed artboards.add must not leave the NEXT panel pointing at the
    same bad slot — the failure path advances xCursor like the success path."""
    src = _jsx()
    m = re.search(r"catch \(eAdd\) \{(.*?)\n      \}", src, re.S)
    assert m, "artboards.add failure handler not found in the .jsx"
    handler = m.group(1)
    assert "xCursor += abWpt + gapPt;" in handler
    assert "rowMaxH" in handler and "bandW" in handler
