"""Tests for the pure preflight helpers in tools/proofer.py.

These cover panel matching and the size / color / resolution decision logic.
They operate on plain dicts (a tiny booth spec, or a pre-built `info` dict),
so no real PDF/image, Ghostscript, Chrome, or network is needed.
"""
import json
import os
import sys

import pytest

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


# ---------- P0-6: unmatched --panel errors; token-boundary filename matching ----------
LETTER_SPEC = {"settings": {}, "panels": [{"name": n, "w": 10, "h": 20}
                                          for n in ("A", "B", "C", "D", "E", "F1")]}


def test_find_panel_explicit_arg_not_found_never_falls_through():
    # the filename would token-match panel A, but the operator asked for Wall_Z:
    # silently checking a DIFFERENT panel is exactly the P0-6 bug
    panel, why = proofer.find_panel(SPEC, "wall_a_final.pdf", "Wall_Z")
    assert panel is None
    assert 'no panel named "Wall_Z"' in why
    assert "Wall A" in why and "Wall AB" in why  # lists the available names


def test_run_checks_explicit_panel_not_found_runs_no_checks(tmp_path):
    # the artwork file does not even exist: if any check ran we'd get an
    # exception, so the clean error return proves checks never started
    r = proofer.run_checks(str(tmp_path / "missing.pdf"), SPEC, "Wall_Z")
    assert set(r) == {"error"}
    assert 'no panel named "Wall_Z"' in r["error"]


def test_find_panel_short_names_are_not_substring_matched():
    # 'revised.pdf' used to match panel D (substring 'd'); 'logo_art.pdf' -> A
    for fname in ("revised.pdf", "logo_art.pdf", "final_v2.pdf"):
        assert proofer.find_panel(LETTER_SPEC, fname, None) == (None, None)


def test_find_panel_token_matches_still_work():
    panel, how = proofer.find_panel(LETTER_SPEC, "F1_art.pdf", None)
    assert panel["name"] == "F1" and how == "matched from filename"
    panel, how = proofer.find_panel(LETTER_SPEC, "wall_a_final.pdf", None)
    assert panel["name"] == "A" and how == "matched from filename"


def test_find_panel_multiword_name_spans_tokens():
    panel, how = proofer.find_panel(SPEC, "wall_ab_v2.pdf", None)
    assert panel["name"] == "Wall AB"


def test_find_panel_equal_specificity_refuses():
    panel, why = proofer.find_panel(LETTER_SPEC, "a_b_final.pdf", None)
    assert panel is None
    assert "equal specificity" in why and "--panel" in why


def test_main_explicit_panel_not_found_exits_nonzero(tmp_path, monkeypatch, capsys):
    sp = tmp_path / "booth_spec.json"
    sp.write_text(json.dumps(SPEC))
    monkeypatch.setattr(sys, "argv", ["proofer.py", str(tmp_path / "art.pdf"),
                                      "--spec", str(sp), "--panel", "Wall_Z"])
    with pytest.raises(SystemExit) as ei:
        proofer.main()
    assert ei.value.code == 2
    assert 'no panel named "Wall_Z"' in capsys.readouterr().out


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


# ---------- P0-4: size check verifies bleed presence ----------
def _pdf_info(media, trim=None, margin=None):
    return {"kind": "pdf", "media_in": media, "trim_in": trim,
            "marks_margin_in": margin, "page_sizes": []}


PANEL_A = SPEC["panels"][0]  # 100 x 200, bleed 1.0, scale 0.5


def test_size_trim_match_without_bleed_warns():
    # media == trim size, no TrimBox -> zero bleed in the file
    st, msg = proofer.check_size(_pdf_info((100, 200)), SPEC, PANEL_A)
    assert st == "WARN"
    assert "no bleed detected" in msg
    assert 'add 1" bleed per side' in msg


def test_size_half_trim_match_without_bleed_warns_scaled():
    st, msg = proofer.check_size(_pdf_info((50, 100)), SPEC, PANEL_A)
    assert st == "WARN"
    assert "no bleed detected" in msg and 'add 0.5" bleed per side' in msg


def test_size_full_plus_bleed_still_passes():
    st, msg = proofer.check_size(_pdf_info((102, 202)), SPEC, PANEL_A)
    assert st == "PASS" and "full + bleed" in msg


def test_size_trim_match_with_real_bleed_margin_passes():
    # TrimBox at trim size, media extends 1" per side -> bleed is present
    st, msg = proofer.check_size(_pdf_info((102, 202), trim=(100, 200), margin=1.0),
                                 SPEC, PANEL_A)
    assert st == "PASS" and "full trim" in msg


def test_size_trimbox_equal_to_media_warns():
    # TrimBox present but media == trim: still zero bleed
    st, msg = proofer.check_size(_pdf_info((100, 200), trim=(100, 200), margin=0.0),
                                 SPEC, PANEL_A)
    assert st == "WARN" and "no bleed detected" in msg


def test_size_raster_at_bare_trim_warns():
    info = {"kind": "raster", "px": (5000, 10000), "dpi": 50}  # 100 x 200 in
    st, msg = proofer.check_size(info, SPEC, PANEL_A)
    assert st == "WARN" and "no bleed detected" in msg


def test_size_raster_with_bleed_passes():
    info = {"kind": "raster", "px": (5100, 10100), "dpi": 50}  # 102 x 202 in
    st, msg = proofer.check_size(info, SPEC, PANEL_A)
    assert st == "PASS"


def test_fix_instructions_no_bleed_warn_gets_entry():
    results = {"size": ("WARN", '100.00" x 200.00" (media (no TrimBox)) matches trim size '
                                '(full trim) but no bleed detected (no TrimBox set) — '
                                'add 1" bleed per side')}
    fixes = proofer.fix_instructions(results, {}, SPEC, PANEL_A)
    assert len(fixes) == 1 and fixes[0]["check"] == "size" and fixes[0]["severity"] == "WARN"
    assert 'Add 1" bleed' in fixes[0]["text"]
    assert '102"' in fixes[0]["text"] and '202"' in fixes[0]["text"]


def test_fix_instructions_raster_cannot_verify_warn_has_no_bleed_entry():
    # the 'cannot verify finished size' WARN is not a bleed finding
    results = {"size": ("WARN", "500x500px, no embedded size/DPI - cannot verify finished size")}
    assert proofer.fix_instructions(results, {}, SPEC, PANEL_A) == []


# ---------- P0-5: printer-marks check fires on real crop marks ----------
def _marks_info(margin):
    return {"kind": "pdf", "marks_margin_in": margin}


def test_marks_margin_over_expected_bleed_warns_full_scale():
    # bleed 1.0, full-scale match: 1.4" margin = marks territory
    st, msg = proofer.check_marks(_marks_info(1.4), SPEC, "full + bleed")
    assert st == "WARN" and 'expected 1"' in msg


def test_marks_margin_equal_to_bleed_passes_full_scale():
    st, msg = proofer.check_marks(_marks_info(1.0), SPEC, "full + bleed")
    assert st == "PASS"


def test_marks_half_scale_margin_at_scaled_bleed_passes():
    # half-scale match: expected bleed 0.5"
    st, msg = proofer.check_marks(_marks_info(0.5), SPEC, "half + bleed")
    assert st == "PASS"


def test_marks_half_scale_oversized_margin_warns():
    st, msg = proofer.check_marks(_marks_info(0.8), SPEC, "half + bleed")
    assert st == "WARN" and 'expected 0.5"' in msg


def test_marks_no_trimbox_is_na():
    assert proofer.check_marks(_marks_info(None), SPEC, "full + bleed")[0] == "NA"
    assert proofer.check_marks({"kind": "raster", "marks_margin_in": None})[0] == "NA"


def test_marks_legacy_heuristic_without_spec():
    # backward compatible: no spec -> old 2.5" threshold
    assert proofer.check_marks(_marks_info(1.4))[0] == "PASS"
    assert proofer.check_marks(_marks_info(2.6))[0] == "WARN"


def test_check_size_records_matched_label_for_marks_threading():
    info = _pdf_info((102, 202))
    proofer.check_size(info, SPEC, PANEL_A)
    assert info["size_match_label"] == "full + bleed"
    info = _pdf_info((33, 33))
    proofer.check_size(info, SPEC, PANEL_A)
    assert info["size_match_label"] is None


# ---------- P0-9: resolution thresholds from the booth JSON ----------
BAND_SPEC = {"settings": {"resolution_ppi": {"min": 100, "max": 200}, "scale": 0.5}}


def test_resolution_band_read_from_spec_with_defaults():
    assert proofer.resolution_band(BAND_SPEC) == (100, 200)
    assert proofer.resolution_band(SPEC) == (120, 150)     # no band -> defaults
    assert proofer.resolution_band(None) == (120, 150)


def test_check_resolution_spec_band_drives_thresholds():
    # 110 ppi fails the default 120 floor but PASSes a min:100 spec
    st, msg = proofer.check_resolution({"kind": "raster", "dpi": 110}, BAND_SPEC)
    assert st == "PASS" and "100" in msg and "200" in msg
    assert proofer.check_resolution({"kind": "raster", "dpi": 90}, BAND_SPEC)[0] == "FAIL"
    st, msg = proofer.check_resolution({"kind": "raster", "dpi": 210}, BAND_SPEC)
    assert st == "WARN" and "200" in msg


def test_check_resolution_full_scale_match_relaxes_floor():
    # spec band 120-150 at the 1/2-scale build; a FULL-scale file at 80 ppi is
    # better printed quality than a passing 150-ppi half-scale file
    st, msg = proofer.check_resolution({"kind": "raster", "dpi": 80}, SPEC, matched_scale=1.0)
    assert st == "PASS"
    assert "relaxed to 60 ppi" in msg              # normalization named in the detail
    # still a floor: 50 ppi fails even relaxed
    assert proofer.check_resolution({"kind": "raster", "dpi": 50}, SPEC,
                                    matched_scale=1.0)[0] == "FAIL"


def test_check_resolution_half_scale_path_never_relaxed():
    # relax-only: half-scale files keep the full 120 floor (invariant 5 -
    # clients are told to deliver 120-150 at the 1/2-scale build)
    st, msg = proofer.check_resolution({"kind": "raster", "dpi": 130}, SPEC, matched_scale=0.5)
    assert st == "PASS" and "relaxed" not in msg
    assert proofer.check_resolution({"kind": "raster", "dpi": 119}, SPEC,
                                    matched_scale=0.5)[0] == "FAIL"


def test_check_resolution_pdf_images_use_spec_band():
    info = {"kind": "pdf", "images": [{"px": (500, 500), "ppi": 110, "how": "placed"}]}
    assert proofer.check_resolution(info)[0] == "FAIL"              # default 120
    st, msg = proofer.check_resolution(info, BAND_SPEC)
    assert st == "PASS" and "100" in msg


def test_fix_instructions_resolution_quotes_spec_band():
    spec = {"settings": {"resolution_ppi": {"min": 100, "max": 200}},
            "panels": [PANEL_A]}
    fixes = proofer.fix_instructions({"resolution": ("FAIL", "low")}, {"min_ppi": 72},
                                     spec, PANEL_A)
    text = fixes[0]["text"]
    assert "100" in text and "200" in text and "at build scale" in text


# ---------- P0-7: REVIEW verdict must render a report; batch must survive ----------
def test_build_report_html_review_verdict_renders():
    # used to raise KeyError('NEEDS REVIEW') and kill the whole batch
    doc = proofer.build_report_html("art.pdf", "Wall A", "matched from filename",
                                    {"size": ("WARN", "no bleed detected")}, "REVIEW")
    assert "NEEDS REVIEW" in doc          # display label
    assert "#F7941E" in doc               # orange REVIEW badge
    # raw PASS/FAIL labels unchanged
    assert "FAIL" in proofer.build_report_html("a.pdf", "A", "x", {}, "FAIL")


def test_badge_has_review_entry():
    assert proofer.BADGE["REVIEW"] == "#F7941E"


def test_batch_crashing_file_does_not_abort_and_review_report_written(tmp_path, monkeypatch, capsys):
    from PIL import Image
    monkeypatch.chdir(tmp_path)
    sp = tmp_path / "booth_spec.json"
    sp.write_text(json.dumps(SPEC))
    bad = tmp_path / "wall_a_bad.pdf"
    bad.write_text("this is not a PDF")               # run_checks raises on it
    good = tmp_path / "wall_a_art.png"                 # grayscale, no DPI ->
    Image.new("L", (50, 50), 255).save(good)           # all-WARN -> REVIEW
    monkeypatch.setattr(sys, "argv", ["proofer.py", str(bad), str(good), "--spec", str(sp)])
    proofer.main()                                     # must not raise
    out = capsys.readouterr().out
    assert "could not process" in out                  # crash reported, batch continued
    assert "REVIEW" in out
    report = tmp_path / "wall_a_art_preflight.html"
    assert report.exists(), "the good file's report must still be produced"
    assert "NEEDS REVIEW" in report.read_text(encoding="utf-8")


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


# ---------- P0-10: marked_preview temp-file + gs hygiene ----------
class _GsResult:
    def __init__(self, rc):
        self.returncode = rc


def test_marked_preview_gs_failure_returns_none_not_the_decoy(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    decoy = tmp_path / "_proof_mark.png"            # the old fixed cwd path
    decoy.write_bytes(b"stale preview from another job")
    monkeypatch.setattr(proofer.subprocess, "run", lambda *a, **k: _GsResult(1))
    assert proofer.marked_preview("art.pdf", {}, SPEC, PANEL_A, []) is None
    assert decoy.read_bytes() == b"stale preview from another job"


def test_marked_preview_gs_rc0_no_output_returns_none(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(proofer.subprocess, "run", lambda *a, **k: _GsResult(0))
    assert proofer.marked_preview("art.pdf", {}, SPEC, PANEL_A, []) is None


def test_marked_preview_uses_only_this_runs_gs_output(tmp_path, monkeypatch):
    from PIL import Image
    monkeypatch.chdir(tmp_path)
    decoy = tmp_path / "_proof_mark.png"
    decoy.write_bytes(b"garbage - not a png")       # would crash PIL if ever opened

    def fake_run(cmd, **kw):
        out = cmd[cmd.index("-o") + 1]
        Image.new("RGB", (120, 60), "white").save(out)
        return _GsResult(0)

    monkeypatch.setattr(proofer.subprocess, "run", fake_run)
    uri = proofer.marked_preview("art.pdf", {}, SPEC, PANEL_A, [])
    assert uri and uri.startswith("data:image/png;base64,")
    assert decoy.read_bytes() == b"garbage - not a png"   # never read or removed
    # the unique temp file is removed by the finally block
    leftovers = [p for p in os.listdir(tmp_path) if p.startswith("_proof_mark_")]
    assert leftovers == []


# ---------- P3-6: scale word, per-candidate tolerance, per-axis dpi ----------
def test_scale_word_derivation():
    assert proofer.scale_word(0.5) == "half"
    assert proofer.scale_word(0.25) == "quarter"
    assert proofer.scale_word(0.75) == "0.75x"


def test_expected_sizes_use_the_actual_scale_word():
    spec = {"settings": {"bleed_per_side_in": 1.0, "scale": 0.25}}
    exp, b, sc = proofer.expected_sizes(spec, {"w": 100, "h": 200})
    assert exp["quarter trim"] == (25.0, 50.0)
    assert exp["quarter + bleed"] == (25.5, 50.5)
    assert "half trim" not in exp                     # no longer mislabeled


def test_expected_sizes_skip_scaled_candidates_at_full_scale():
    spec = {"settings": {"bleed_per_side_in": 1.0, "scale": 1}}
    exp, _, _ = proofer.expected_sizes(spec, {"w": 100, "h": 200})
    assert set(exp) == {"full trim", "full + bleed"}
    spec_none = {"settings": {"bleed_per_side_in": 1.0, "scale": None}}
    exp2, _, _ = proofer.expected_sizes(spec_none, {"w": 100, "h": 200})
    assert set(exp2) == {"full trim", "full + bleed"}


def test_size_match_per_candidate_tolerance():
    spec = {"settings": {"bleed_per_side_in": 1.0, "scale": 0.5}}
    exp, _, sc = proofer.expected_sizes(spec, {"w": 100, "h": 200})
    # 0.05" error on a half-scale candidate = 0.1" at print size -> rejected
    assert proofer.size_match(50.05, 100, exp, sc) is None
    # the same absolute error on a full-scale candidate stays within TOL
    assert proofer.size_match(100.05, 200, exp, sc) == "full trim"
    # a truly half-scale file still matches (error under TOL*sc)
    assert proofer.size_match(50.03, 100.0, exp, sc) == "half trim"
    # legacy call without sc keeps the old flat tolerance
    assert proofer.size_match(50.05, 100, exp) == "half trim"


def test_fix_instructions_scale_word_follows_the_spec():
    panel = {"name": "A", "w": 100, "h": 200}
    res = {"size": ("FAIL", "no match")}
    q = proofer.fix_instructions(res, {"kind": "pdf"},
                                 {"settings": {"bleed_per_side_in": 1.0, "scale": 0.25}}, panel)
    assert "Quarter scale" in q[0]["text"] and '25.5" × 50.5"' in q[0]["text"]
    full = proofer.fix_instructions(res, {"kind": "pdf"},
                                    {"settings": {"bleed_per_side_in": 1.0, "scale": 1}}, panel)
    assert "also accepted" not in full[0]["text"]     # no scaled candidates to offer
    warn = proofer.fix_instructions({"size": ("WARN", "no bleed detected")}, {"kind": "pdf"},
                                    {"settings": {"bleed_per_side_in": 1.0, "scale": 0.25}}, panel)
    assert "quarter-scale files" in warn[0]["text"]


def test_analyze_raster_keeps_both_dpi_axes_and_grades_the_worst(tmp_path):
    from PIL import Image
    p = tmp_path / "art.png"
    Image.new("RGB", (300, 300), "white").save(p, dpi=(300, 72))
    info = proofer.analyze_raster(str(p))
    assert info["dpi_xy"] == (300, 72)
    assert info["dpi"] == 72                          # worst axis, not x-axis-only


def test_check_size_per_axis_math_and_stretch_warn():
    spec = {"settings": {"bleed_per_side_in": 1.0, "scale": 0.5}}
    panel = {"name": "A", "w": 100, "h": 200}
    # 51" x 101" (= half + bleed) at a uniform 100 dpi: PASS
    ok = {"kind": "raster", "px": (5100, 10100), "dpi": 100, "dpi_xy": (100, 100)}
    assert proofer.check_size(ok, spec, panel)[0] == "PASS"
    # same pixels tagged 100 x 96 dpi: x/y density differs > 1% -> WARN, sizes per axis
    bad = {"kind": "raster", "px": (5100, 10100), "dpi": 96, "dpi_xy": (100, 96)}
    st, msg = proofer.check_size(bad, spec, panel)
    assert st == "WARN"
    assert "stretched" in msg and "100 x 96 dpi" in msg
    assert "105.21" in msg                             # 10100/96 — the per-axis height
