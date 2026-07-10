"""P0-15 guards for the Illustrator production generator (.jsx).

There is no automated Illustrator run (the .jsx only executes inside Adobe
Illustrator — see the manual smoke checklist in CLAUDE.md), so these tests pin
what CAN be checked outside it: the file stays syntactically valid JavaScript,
and the abort-on-bad-spec / door_marks / mirroring / layout-failure behaviors
are present in the source rather than silently reverted.
"""
import os
import re
import shutil
import subprocess
import tempfile

import pytest

JSX_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "tools", "SEE_Wall_Template_Generator.jsx")


def _jsx():
    return open(JSX_PATH, encoding="utf-8").read()


def _find_node():
    node = shutil.which("node")
    if node:
        return node
    for cand in ("/opt/node22/bin/node", "/usr/local/bin/node"):
        if os.path.exists(cand):
            return cand
    return None


def test_jsx_is_valid_javascript_syntax():
    node = _find_node()
    if not node:
        pytest.skip("node not available for the .jsx syntax gate")
    # node refuses the .jsx extension; check a .js copy of the same bytes
    with tempfile.TemporaryDirectory() as td:
        js = os.path.join(td, "generator_check.js")
        shutil.copyfile(JSX_PATH, js)
        p = subprocess.run([node, "--check", js], capture_output=True, text=True)
        assert p.returncode == 0, f"node --check failed:\n{p.stderr}"


def test_load_spec_aborts_instead_of_building_the_wrong_booth():
    src = _jsx()
    # every failure path returns null (abort); the example is Cancel-only
    assert src.count("return null;") >= 4
    assert "f == null" in src                      # explicit Cancel check
    assert "!f.exists" in src                      # missing file -> abort
    assert 'f.open("r")' in src and "Could not open the booth spec" in src
    assert "if (!SPEC)" in src                     # build block guarded
    # the old silent-fallback message must be gone
    assert "using the built-in example instead" not in src


def test_parse_json_safe_strips_bom_and_reports_the_parse_error():
    src = _jsx()
    assert re.search(r"replace\(/\^\\uFEFF/", src)          # BOM strip
    assert "Booth spec is not valid JSON: " in src          # parse error text included


def test_jsx_ports_door_marks_from_the_python_templates():
    src = _jsx()
    assert "function drawDoorMarks" in src
    assert "drawDoorMarks(lDoor, lLabel, p, trimLeftXpt, trimBottomYpt" in src  # actually called
    # same defaults the Python side uses: width falls back to the standard door
    # leaf, holes only for an explicit left/right side
    assert "DOOR.panel_w_in" in src
    assert 'dmSide === "left" || dmSide === "right"' in src
    # the nested door leaf (a real door centered inside a wider panel, e.g. an
    # Aluvision door in a ~39" bay) must be ported too, or the production template
    # would draw only the panel and drift from the client template
    assert "dm.leaf" in src


def test_jsx_ports_door_template_profiles():
    # the warehouse-keyed door profiles + door_template resolution must exist in the
    # .jsx too (mirrors preview_templates.DOOR_PROFILES / resolve_door_standard) so a
    # booth file's `door_template` picks the same door in production as in the preview
    src = _jsx()
    assert "DOOR_PROFILES" in src
    assert "aluvision" in src and "bmatrix" in src
    assert "SPEC.door_template" in src
    assert 'handle_style' in src                       # slot vs holes gate is ported


def test_jsx_continuous_oversize_message_matches_the_flag():
    src = _jsx()
    assert 'p.oversize_mode === "continuous"' in src
    assert "printed as ONE continuous piece" in src
    assert "tile/seam separately" in src                    # non-continuous keeps its wording


def test_jsx_bands_layout_height_and_reports_canvas_failures_separately():
    src = _jsx()
    assert "MAX_COL_H_PT = 220 * PT" in src                 # cumulative height is now capped
    assert "xBase = xBase + bandW + gapPt" in src           # new band shifts right
    assert "var failed = []" in src
    assert "COULD NOT CREATE (layout/canvas error — rerun or report):" in src
    # artboards.add failures must NOT land in the tile/seam (oversized) bucket
    assert 'failed.push(displayName + "  (" + eAdd + ")")' in src
    assert "artboard could not be created" not in src


def test_claude_md_has_the_manual_illustrator_checklist():
    md = open(os.path.join(os.path.dirname(JSX_PATH), "..", "CLAUDE.md"), encoding="utf-8").read()
    assert "Manual Illustrator smoke checklist" in md
    assert "Side B" in md and "door_marks" in md
    assert "corrupted JSON" in md.lower() or "corrupted json" in md.lower()


def test_jsx_mirrors_side_b():
    src = _jsx()
    assert "var mirrored = (sIdx === 1);" in src            # Side B of a double-sided panel
    # zones and door_marks mirror x -> w - x - zw; the door hand flips
    assert "panel.w - zn.x - zn.w" in src
    assert "panel.w - dmXin - dmWin" in src
    assert 'mirrored ? ((p.door === "left") ? "right" : "left") : p.door' in src
    # zones/door_marks calls actually receive the flag
    assert "drawZones(lZone, lLabel, p, trimLeftXpt, trimBottomYpt, mirrored)" in src
    assert "drawDoorMarks(lDoor, lLabel, p, trimLeftXpt, trimBottomYpt, mirrored)" in src


def test_default_spec_is_a_labeled_synthetic_demo():
    """P3-4: the Cancel-path DEFAULT_SPEC is a tiny synthetic demo, not an
    embedded copy of the shipped example booth (the Mama's Creations copy had
    already drifted from examples/1_booth_spec_example.json)."""
    src = _jsx()
    assert "built-in demo — not a real booth" in src
    assert "Mama's Creations" not in src
    # Cancel alert warns the demo is demo data only
    assert "pick the real booth JSON for production" in src
    # the demo stays tiny: exactly two panels inside the DEFAULT_SPEC literal
    block = re.search(r"var DEFAULT_SPEC = \{.*?\n\};", src, re.S).group(0)
    assert len(re.findall(r'name: "Demo_', block)) == 2
