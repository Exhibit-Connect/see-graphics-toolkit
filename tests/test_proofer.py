"""Tests for the pure preflight helpers in tools/proofer.py.

These cover panel matching and the size / color / resolution decision logic.
They operate on plain dicts (a tiny booth spec, or a pre-built `info` dict),
so no real PDF/image, Ghostscript, Chrome, or network is needed.
"""
import proofer


SPEC = {
    "settings": {"bleed_per_side_in": 1.0, "scale": 0.5},
    "panels": [
        {"name": "Wall A", "w": 100, "h": 200},
        {"name": "Wall AB", "w": 10, "h": 20},
    ],
}


def test_norm_strips_to_alnum_lowercase():
    assert proofer.norm("Wall A / Left!") == "wallaleft"


def test_unverified_panels_lists_needs_confirm():
    spec = {"panels": [
        {"name": "A", "w": 10, "h": 20},                         # verified (no flag)
        {"name": "B", "w": 30, "h": 40, "needs_confirm": True},   # AI/OCR-seeded
        {"name": "C", "w": 5, "h": 5, "needs_confirm": False},
    ]}
    assert proofer.unverified_panels(spec) == ["B"]
    assert proofer.unverified_panels({"panels": []}) == []


def test_expected_sizes_full_half_and_bleed():
    expected, b, sc = proofer.expected_sizes(SPEC, SPEC["panels"][0])
    assert b == 1.0 and sc == 0.5
    assert expected["full trim"] == (100, 200)
    assert expected["full + bleed"] == (102.0, 202.0)
    assert expected["half trim"] == (50.0, 100.0)
    assert expected["half + bleed"] == (51.0, 101.0)


def test_size_match_within_tolerance_and_rotation():
    expected, _, _ = proofer.expected_sizes(SPEC, SPEC["panels"][0])
    assert proofer.size_match(100, 200, expected) == "full trim"
    # TOL is 0.08in, so a 0.05in drift still matches
    assert proofer.size_match(100.05, 199.97, expected) == "full trim"
    # swapped w/h is reported as rotated
    assert proofer.size_match(200, 100, expected) == "full trim (rotated)"
    # half-scale size is also acceptable
    assert proofer.size_match(50, 100, expected) == "half trim"


def test_size_match_returns_none_when_nothing_matches():
    expected, _, _ = proofer.expected_sizes(SPEC, SPEC["panels"][0])
    assert proofer.size_match(33, 33, expected) is None


def test_find_panel_explicit_arg_wins():
    panel, how = proofer.find_panel(SPEC, "anything.pdf", "Wall A")
    assert panel["name"] == "Wall A"
    assert how == "named explicitly"


def test_find_panel_longest_filename_match_wins():
    # filename contains both "wallab" and "walla"; longest name should win
    panel, how = proofer.find_panel(SPEC, "client_WallAB_final.pdf", None)
    assert panel["name"] == "Wall AB"
    assert how == "matched from filename"


def test_find_panel_no_match_returns_none():
    assert proofer.find_panel(SPEC, "random_artwork.pdf", None) == (None, None)


def test_check_color_raster_modes():
    assert proofer.check_color({"kind": "raster", "mode": "CMYK"})[0] == "PASS"
    assert proofer.check_color({"kind": "raster", "mode": "RGB"})[0] == "FAIL"
    assert proofer.check_color({"kind": "raster", "mode": "L"})[0] == "WARN"


def test_check_color_pdf_flags_rgb():
    # RGB present anywhere is a FAIL even alongside CMYK
    assert proofer.check_color({"kind": "pdf", "colors": {"RGB", "CMYK"}})[0] == "FAIL"
    assert proofer.check_color({"kind": "pdf", "colors": {"CMYK"}})[0] == "PASS"
    # nothing detected -> can't confirm, WARN
    assert proofer.check_color({"kind": "pdf", "colors": set()})[0] == "WARN"


def test_check_resolution_raster_thresholds():
    # boundary: 120 is the floor (PASS), below it FAILs
    assert proofer.check_resolution({"kind": "raster", "dpi": 120})[0] == "PASS"
    assert proofer.check_resolution({"kind": "raster", "dpi": 119})[0] == "FAIL"
    # 150 is the ceiling (PASS), above it is overkill (WARN)
    assert proofer.check_resolution({"kind": "raster", "dpi": 150})[0] == "PASS"
    assert proofer.check_resolution({"kind": "raster", "dpi": 151})[0] == "WARN"
    # missing DPI -> can't verify
    assert proofer.check_resolution({"kind": "raster", "dpi": None})[0] == "WARN"


def test_check_resolution_pdf_vector_only_passes():
    # genuinely vector (no analysis gaps) -> PASS retained
    assert proofer.check_resolution({"kind": "pdf", "images": []})[0] == "PASS"
    assert proofer.check_resolution({"kind": "pdf", "images": [],
                                     "analysis_gaps": []})[0] == "PASS"


def test_check_resolution_pdf_gaps_block_vector_pass():
    # analysis failures must never yield the vector-only PASS
    st, msg = proofer.check_resolution({"kind": "pdf", "images": [],
                                        "analysis_gaps": ["XObject '/Im1' could not be parsed: boom"]})
    assert st == "WARN"
    assert "could not fully analyze 1 object(s)" in msg


def test_check_color_gaps_block_cmyk_pass():
    st, msg = proofer.check_color({"kind": "pdf", "colors": {"CMYK"},
                                   "analysis_gaps": ["unidentified colorspace could not be resolved"]})
    assert st == "WARN" and "could not be analyzed" in msg
    # RGB stays FAIL even with gaps
    assert proofer.check_color({"kind": "pdf", "colors": {"RGB"},
                                "analysis_gaps": ["x"]})[0] == "FAIL"


def test_check_fonts_form_gap_blocks_outlined_pass():
    st, msg = proofer.check_fonts({"kind": "pdf", "fonts": 0,
                                   "analysis_gaps": ["form XObject '/Fm1' could not be analyzed: boom"]})
    assert st == "WARN" and "cannot confirm text is outlined" in msg
    # no gaps -> PASS unchanged
    assert proofer.check_fonts({"kind": "pdf", "fonts": 0})[0] == "PASS"


# ---------- fix-it instructions (Feature 3) ----------
PANEL = SPEC["panels"][0]   # Wall A: 100 x 200, bleed 1, scale 0.5


def test_fix_instructions_empty_when_all_pass():
    results = {"size": ("PASS", ""), "color": ("PASS", ""), "resolution": ("PASS", ""),
               "fonts": ("PASS", ""), "marks": ("PASS", ""), "spelling": ("PASS", "")}
    assert proofer.fix_instructions(results, {}, SPEC, PANEL) == []


def test_fix_instructions_size_fail_names_the_target_size():
    fixes = proofer.fix_instructions({"size": ("FAIL", "wrong")}, {}, SPEC, PANEL)
    assert len(fixes) == 1 and fixes[0]["check"] == "size"
    text = fixes[0]["text"]
    assert '100"' in text and '200"' in text          # full trim
    assert '102"' in text and '202"' in text           # + 1" bleed each side
    assert "bleed" in text.lower()


def test_fix_instructions_rgb_says_convert_to_cmyk():
    fixes = proofer.fix_instructions({"color": ("FAIL", "contains RGB")}, {}, SPEC, PANEL)
    assert fixes[0]["check"] == "color" and "CMYK" in fixes[0]["text"]


def test_fix_instructions_grayscale_warn_is_distinct():
    fixes = proofer.fix_instructions({"color": ("WARN", "L (grayscale)")}, {}, SPEC, PANEL)
    assert fixes[0]["check"] == "color"
    assert "black & white" in fixes[0]["text"] or "grayscale" in fixes[0]["text"]


def test_fix_instructions_resolution_fail_cites_ppi():
    # PDFs carry min_ppi …
    fixes = proofer.fix_instructions({"resolution": ("FAIL", "low")}, {"min_ppi": 72}, SPEC, PANEL)
    assert fixes[0]["check"] == "resolution"
    assert "72" in fixes[0]["text"] and "120" in fixes[0]["text"]


def test_fix_instructions_resolution_fail_uses_raster_dpi():
    # … rasters carry dpi (regression: must not print "about None ppi")
    fixes = proofer.fix_instructions({"resolution": ("FAIL", "low")}, {"dpi": 72}, SPEC, PANEL)
    assert "72" in fixes[0]["text"] and "None" not in fixes[0]["text"]


def test_fix_instructions_resolution_fail_no_ppi_is_clean():
    fixes = proofer.fix_instructions({"resolution": ("FAIL", "low")}, {}, SPEC, PANEL)
    assert "None" not in fixes[0]["text"] and "under 120 ppi" in fixes[0]["text"]


def test_fix_instructions_spelling_lists_words_from_message():
    fixes = proofer.fix_instructions({"spelling": ("WARN", "2 word(s) to review: Mamas, Creationz")},
                                     {}, SPEC, PANEL)
    assert fixes[0]["check"] == "spelling" and "Creationz" in fixes[0]["text"]


def test_overlay_boxes_insets_by_fraction():
    assert proofer.overlay_boxes(100, 200, 0.1, 0.05) == (10, 10, 90, 190)
