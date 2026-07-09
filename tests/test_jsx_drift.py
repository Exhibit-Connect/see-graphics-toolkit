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
