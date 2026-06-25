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
    assert proofer.check_resolution({"kind": "pdf", "images": []})[0] == "PASS"
