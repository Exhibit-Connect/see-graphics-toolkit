"""Tests for the deterministic, offline text-parsing helpers in tools/intake.py.

These cover the "reliable floor" pass that pulls panel names + sizes out of a
handoff's extracted text. No PDF, Ghostscript, network, or AI calls involved -
the functions under test take plain strings and return plain data.
"""
import intake


def test_norm_name_strips_to_alnum_lowercase():
    # used to compare panel names across pages regardless of spacing/punctuation
    assert intake.norm_name("Wall A.1 / Left!") == "walla1left"
    assert intake.norm_name("") == ""


def test_parse_panels_basic_extraction():
    text = 'Wall A: 78.12" x 173.32"\nWall B: 40 x 50\n'
    panels, conflicts = intake.parse_panels(text)
    assert panels == [
        {"name": "Wall A", "w": 78.12, "h": 173.32},
        {"name": "Wall B", "w": 40.0, "h": 50.0},
    ]
    assert conflicts == []


def test_parse_panels_skips_blocklisted_labels():
    # "Note", "Trim", "Scale" etc. are layout labels, not real panels
    text = "Note: 10 x 20\nTrim: 5 x 5\nWall C: 12 x 12\n"
    panels, _ = intake.parse_panels(text)
    assert [p["name"] for p in panels] == ["Wall C"]


def test_parse_panels_filters_out_of_range_dimensions():
    # valid panel dimensions must be within 1..600 inches
    text = "Huge: 700 x 50\nTiny: 0.5 x 0.5\nOk: 5 x 5\n"
    panels, _ = intake.parse_panels(text)
    assert [p["name"] for p in panels] == ["Ok"]


def test_parse_panels_dedupes_and_records_conflicts():
    # same name + same size -> kept once, no conflict
    panels_same, conflicts_same = intake.parse_panels("Wall A: 10 x 20\nWall A: 10 x 20\n")
    assert len(panels_same) == 1
    assert conflicts_same == []

    # same name + different size -> first kept, conflict reported
    panels_diff, conflicts_diff = intake.parse_panels("Wall A: 10 x 20\nWall A: 11 x 21\n")
    assert panels_diff == [{"name": "Wall A", "w": 10.0, "h": 20.0}]
    assert conflicts_diff == [("Wall A", (10.0, 20.0), (11.0, 21.0))]


def test_parse_panels_empty_input():
    assert intake.parse_panels("") == ([], [])


def test_reconcile_flags_per_wall_disagreement():
    panels, _ = intake.parse_panels("Counter: 30 x 40\n")
    # a per-wall page lists the same panel at a different size -> flagged
    secondary = 'Counter\n31" x 41"\n'
    assert intake.reconcile(panels, secondary) == [("Counter", (30.0, 40.0), (31.0, 41.0))]


def test_reconcile_silent_when_sizes_agree():
    panels, _ = intake.parse_panels("Counter: 30 x 40\n")
    assert intake.reconcile(panels, 'Counter\n30" x 40"\n') == []


def test_ai_surface_lines_shows_size_only_when_handoff_printed_it():
    # the model is told not to guess sizes; a panel without dims_shown is flagged,
    # never rendered with an invented number
    ai = {"_status": "live", "panels": [
        {"name": "Back Wall", "w": 120, "h": 96, "dims_shown": True, "finish": "fabric"},
        {"name": "Tower", "w": None, "h": None, "dims_shown": False, "finish": "fabric"},
    ]}
    lines = intake.ai_surface_lines(ai)
    assert any("Back Wall" in ln and "120" in ln for ln in lines)
    assert any("Tower" in ln and "NOT in handoff" in ln for ln in lines)


def test_ai_surface_lines_empty_on_non_live_payloads():
    assert intake.ai_surface_lines({"_status": "dry-run"}) == []
    assert intake.ai_surface_lines({"_status": "error"}) == []
    assert intake.ai_surface_lines(None) == []


def test_ai_seed_panels_seeds_only_shown_dims_and_flags_the_rest():
    ai = {"_status": "live", "panels": [
        {"name": "E", "w": 253.875, "h": 153.8125, "dims_shown": True, "finish": "fabric", "sided": "single"},
        {"name": "Back Wall", "w": None, "h": None, "dims_shown": False, "finish": "fabric"},
    ]}
    seeded, undim = intake.ai_seed_panels(ai)
    assert [p["name"] for p in seeded] == ["E"]
    assert seeded[0]["w"] == 253.875 and seeded[0]["h"] == 153.8125
    assert seeded[0]["needs_confirm"] is True and "AI vision" in seeded[0]["_source"]
    assert undim == ["Back Wall"]      # seen but no printed size -> flagged, never invented


def test_ai_seed_panels_treats_dims_shown_false_as_undimensioned_even_with_numbers():
    # if the model fills numbers but admits dims_shown is false, don't seed them as fact
    ai = {"_status": "live", "panels": [
        {"name": "Guess", "w": 100, "h": 50, "dims_shown": False, "finish": "vinyl"},
    ]}
    seeded, undim = intake.ai_seed_panels(ai)
    assert seeded == [] and undim == ["Guess"]


def test_ai_seed_panels_empty_on_non_live():
    assert intake.ai_seed_panels({"_status": "dry-run"}) == ([], [])
    assert intake.ai_seed_panels(None) == ([], [])


def test_parse_graphic_key_reads_labels_and_dims():
    # the exact shape OCR returns for a real handoff's "Graphic Key"
    text = ('Graphic Key\n'
            'C 107.325"w x 153.8125"h\n'
            'E 253.875"w x 153.8125"h\n'
            'K 78.75"w x 35.433"h\n')
    panels, conflicts = intake.parse_graphic_key(text)
    assert panels == [
        {"name": "C", "w": 107.325, "h": 153.8125},
        {"name": "E", "w": 253.875, "h": 153.8125},
        {"name": "K", "w": 78.75, "h": 35.433},
    ]
    assert conflicts == []


def test_parse_graphic_key_expands_ranges():
    # "H1-H2 ..." means H1 AND H2 share that size -> two panels
    panels, conflicts = intake.parse_graphic_key('H1-H2 39.0625"w x 153.8125"h\n')
    assert [p["name"] for p in panels] == ["H1", "H2"]
    assert all(p["w"] == 39.0625 and p["h"] == 153.8125 for p in panels)
    assert conflicts == []


def test_parse_graphic_key_ignores_non_key_lines():
    # headers / prose / out-of-range numbers are not panels
    text = "Graphic Key\nSome notes here\nBooth is 30x30\nC 700\"w x 50\"h\n"
    assert intake.parse_graphic_key(text) == ([], [])   # 700 is out of the 1..600 range


# ---------- P1-2: full range expansion, unit letters, OCR conflicts, norm dedupe ----------
def test_parse_graphic_key_expands_full_numeric_range():
    # 'H1-H4' seeds H1..H4 — splitting on '-' used to keep only the endpoints,
    # silently dropping H2/H3 from the draft
    panels, conflicts = intake.parse_graphic_key('H1-H4 39.0625"w x 153.8125"h\n')
    assert [p["name"] for p in panels] == ["H1", "H2", "H3", "H4"]
    assert all(p["w"] == 39.0625 and p["h"] == 153.8125 for p in panels)
    assert conflicts == []


def test_parse_graphic_key_expands_letter_range():
    panels, conflicts = intake.parse_graphic_key('C-E 107.325"w x 153.8125"h\n')
    assert [p["name"] for p in panels] == ["C", "D", "E"]
    assert conflicts == []


def test_parse_graphic_key_unexpandable_range_keeps_endpoints_and_notes_it():
    panels, conflicts = intake.parse_graphic_key('A1-B2 39"w x 50"h\n')
    assert [p["name"] for p in panels] == ["A1", "B2"]
    assert any(isinstance(c, str) and "could not be fully expanded" in c for c in conflicts)


def test_parse_graphic_key_repeated_label_two_sizes_is_a_conflict():
    panels, conflicts = intake.parse_graphic_key('C 10"w x 20"h\nC 12"w x 20"h\n')
    assert [p["name"] for p in panels] == ["C"]
    assert panels[0]["w"] == 10.0                       # first size kept
    assert ("C", (10.0, 20.0), (12.0, 20.0)) in conflicts


def test_parse_panels_honors_height_first_unit_letters():
    # '96"h x 48"w' is height-first: the unit letters must not be discarded
    panels, conflicts = intake.parse_panels('Wall A: 96"h x 48"w\n')
    assert panels == [{"name": "Wall A", "w": 48.0, "h": 96.0}]
    assert conflicts == []


def test_parse_panels_width_first_unchanged():
    panels, conflicts = intake.parse_panels('Wall A: 48"w x 96"h\n')
    assert panels == [{"name": "Wall A", "w": 48.0, "h": 96.0}]
    assert conflicts == []


def test_parse_panels_contradicting_units_recorded_as_conflict():
    panels, conflicts = intake.parse_panels('Wall A: 96"h x 48"h\n')
    assert [p["name"] for p in panels] == ["Wall A"]     # kept as written...
    assert any(isinstance(c, str) and "contradictory unit labels" in c and "Wall A" in c
               for c in conflicts)                       # ...but flagged for a human


def test_parse_panels_dedupes_on_normalized_name():
    # 'Wall A' / 'WALL A' are ONE panel; the second size is a conflict, not a twin
    panels, conflicts = intake.parse_panels("Wall A: 10 x 20\nWALL A: 12 x 20\n")
    assert panels == [{"name": "Wall A", "w": 10.0, "h": 20.0}]
    assert conflicts == [("Wall A", (10.0, 20.0), (12.0, 20.0))]
    # same size under a different casing -> silently one panel
    panels2, conflicts2 = intake.parse_panels("Wall A: 10 x 20\nWALL A: 10 x 20\n")
    assert len(panels2) == 1 and conflicts2 == []


def test_main_ocr_conflicts_reach_the_review(monkeypatch, tmp_path):
    # a graphic key OCR'd with the same label at two sizes must surface in the
    # review file, not be discarded by the OCR branch
    monkeypatch.chdir(tmp_path)
    _blank_pdf(tmp_path / "deck.pdf")                    # no text -> OCR branch
    monkeypatch.setattr(intake, "ocr_pages",
                        lambda *a, **k: ('C 10"w x 20"h\nC 12"w x 20"h\n', []))
    monkeypatch.setattr(intake.sys, "argv", ["intake.py", "deck.pdf", "--job", "OCR Job"])
    intake.main()
    spec = json.load(open("booth_spec_OCR_Job_DRAFT.json", encoding="utf-8-sig"))
    assert [p["name"] for p in spec["panels"]] == ["C"]
    assert spec["_intake"]["conflicts"] == [{"name": "C", "a": [10.0, 20.0], "b": [12.0, 20.0]}]
    review = open("OCR_Job_intake_review.md", encoding="utf-8").read()
    assert "Dimension conflicts" in review and "10.0x20.0 vs 12.0x20.0" in review


# ---------- P1-1: gs/tesseract hygiene - checked results, temp dirs, warnings ----------
import json
import os

import pytest


class _Proc:
    def __init__(self, returncode=0, stdout="", stderr=b""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _gs_writer(fail_pages=(), stderr=b""):
    """Fake subprocess.run: creates the -o target like gs would, unless the page
    is in fail_pages (then rc=1, nothing written)."""
    def run(cmd, **kw):
        if "-o" in cmd:
            page = int(next(a for a in cmd if a.startswith("-dFirstPage=")).split("=")[1])
            if page in fail_pages:
                return _Proc(1, stderr=stderr)
            with open(cmd[cmd.index("-o") + 1], "wb") as f:
                f.write(b"\x89PNG page render")
            return _Proc(0)
        return _Proc(0, stdout="OCR TEXT")
    return run


def test_render_pages_gs_failure_recorded_in_warnings_not_images(monkeypatch, tmp_path):
    monkeypatch.setattr(intake, "GS", "gs")
    imgs, warns = intake.render_pages("x.pdf", 3, run=_gs_writer(fail_pages=(2,), stderr=b"gs blew up"))
    try:
        assert len(imgs) == 2
        assert len(warns) == 1
        assert "page 2" in warns[0] and "rc 1" in warns[0] and "gs blew up" in warns[0]
    finally:
        for p in imgs:
            os.remove(p)


def test_render_pages_never_picks_up_stale_fixed_path_file(monkeypatch, tmp_path):
    # a decoy at the OLD fixed cwd name must never become "this run's" page
    monkeypatch.chdir(tmp_path)
    decoy = tmp_path / "_intake_p1.png"
    decoy.write_bytes(b"stale page from another job")
    monkeypatch.setattr(intake, "GS", "gs")
    imgs, warns = intake.render_pages("x.pdf", 1, run=lambda *a, **k: _Proc(1))
    assert imgs == []                       # nothing produced -> nothing returned
    assert warns and "page 1" in warns[0]
    assert decoy.read_bytes() == b"stale page from another job"


def test_render_pages_gs_missing_returns_graceful_warning(monkeypatch):
    monkeypatch.setattr(intake, "GS", None)
    imgs, warns = intake.render_pages("x.pdf", 4)
    assert imgs == []
    assert warns and "Ghostscript not installed" in warns[0]


def test_render_pages_processes_all_pages_by_default(monkeypatch):
    monkeypatch.setattr(intake, "GS", "gs")
    imgs, warns = intake.render_pages("x.pdf", 9, run=_gs_writer())
    try:
        assert len(imgs) == 9               # old cap was 5; default is now ALL pages
        assert warns == []
    finally:
        for p in imgs:
            os.remove(p)


def test_render_pages_cap_is_disclosed(monkeypatch):
    monkeypatch.setattr(intake, "GS", "gs")
    imgs, warns = intake.render_pages("x.pdf", 9, max_pages=2, run=_gs_writer())
    try:
        assert len(imgs) == 2
        assert any("read 2 of 9 pages" in w and "skipped pages 3-9" in w for w in warns)
    finally:
        for p in imgs:
            os.remove(p)


def test_ocr_pages_tesseract_failure_recorded_and_tmpdir_cleaned(monkeypatch, tmp_path):
    monkeypatch.setattr(intake, "GS", "gs")
    monkeypatch.setattr(intake, "TESSERACT", "/fake/tesseract")
    made = []

    def run(cmd, **kw):
        if "-o" in cmd:
            out = cmd[cmd.index("-o") + 1]
            made.append(out)
            with open(out, "wb") as f:
                f.write(b"\x89PNG")
            return _Proc(0)
        raise OSError("tesseract exploded")

    text, warns = intake.ocr_pages("x.pdf", 2, run=run)
    assert text == ""
    assert len(warns) == 2 and all("tesseract failed" in w for w in warns)
    assert made and not any(os.path.exists(p) for p in made)   # temp dir removed


def test_ocr_pages_missing_tools_warn_instead_of_silence(monkeypatch):
    monkeypatch.setattr(intake, "TESSERACT", None)
    text, warns = intake.ocr_pages("x.pdf", 2)
    assert text == "" and any("tesseract not installed" in w for w in warns)
    monkeypatch.setattr(intake, "TESSERACT", "/fake/tesseract")
    monkeypatch.setattr(intake, "GS", None)
    text, warns = intake.ocr_pages("x.pdf", 2)
    assert text == "" and any("Ghostscript not installed" in w for w in warns)


def test_ai_enrich_dry_run_leaves_no_page_pngs(monkeypatch, tmp_path):
    import ai_client
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(intake, "GS", "gs")
    monkeypatch.setattr(intake.subprocess, "run", _gs_writer())
    monkeypatch.setattr(ai_client, "available", lambda: False)
    ai = intake.ai_enrich("x.pdf", 3, [])
    assert ai["_status"] == "dry-run"
    assert ai["_pages_rendered"] == 3
    assert (tmp_path / "_intake_ai_dryrun.json").exists()
    assert list(tmp_path.glob("_intake_p*.png")) == []      # no cwd litter
    assert list(tmp_path.glob("**/*.png")) == []            # temp pages cleaned up too


def _blank_pdf(path, pages=1):
    from pypdf import PdfWriter
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=200, height=200)
    with open(path, "wb") as f:
        w.write(f)


def test_draft_spec_includes_tbd_job_number_and_pending_entry(monkeypatch, tmp_path):
    # P1-5: intake drafts carry job_number 'TBD' (visible pending) so the
    # dashboard/name-join and the proof placeholder gate both see it
    monkeypatch.chdir(tmp_path)
    _blank_pdf(tmp_path / "deck.pdf")
    monkeypatch.setattr(intake, "ocr_pages", lambda *a, **k: ("", []))
    monkeypatch.setattr(intake.sys, "argv", ["intake.py", "deck.pdf", "--job", "Num Job"])
    intake.main()
    spec = json.load(open("booth_spec_Num_Job_DRAFT.json", encoding="utf-8-sig"))
    assert spec["job"]["job_number"] == "TBD"
    assert any("job number" in p for p in spec["pending_inputs"])


def test_main_surfaces_tool_warnings_in_review_and_spec(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    _blank_pdf(tmp_path / "deck.pdf")                       # no text -> OCR branch
    monkeypatch.setattr(intake, "ocr_pages",
                        lambda *a, **k: ("", ["page 1: Ghostscript render failed (rc 1): boom"]))
    monkeypatch.setattr(intake.sys, "argv", ["intake.py", "deck.pdf", "--job", "Warn Job"])
    intake.main()
    spec = json.load(open("booth_spec_Warn_Job_DRAFT.json", encoding="utf-8-sig"))
    assert spec["_intake"]["warnings"] == ["page 1: Ghostscript render failed (rc 1): boom"]
    review = open("Warn_Job_intake_review.md", encoding="utf-8").read()
    assert "### Tool warnings" in review and "boom" in review
    assert "tool warning" in capsys.readouterr().out


# ---------- P1-3: friendly .eps error, overwrite guard, argparse ----------
def test_postscript_eps_exits_with_export_guidance_not_traceback(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "art.eps").write_bytes(b"%!PS-Adobe-3.0 EPSF-3.0\nnewpath 0 0 moveto\nshowpage\n")
    monkeypatch.setattr(intake.sys, "argv", ["intake.py", "art.eps"])
    with pytest.raises(SystemExit) as ei:
        intake.main()
    assert ei.value.code == 2
    out = capsys.readouterr().out
    assert "PostScript-only" in out and "export a PDF" in out
    assert list(tmp_path.glob("booth_spec_*")) == []     # nothing half-written


def test_unsupported_extension_exits_nonzero(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "handoff.docx").write_bytes(b"not a pdf")
    monkeypatch.setattr(intake.sys, "argv", ["intake.py", "handoff.docx"])
    with pytest.raises(SystemExit) as ei:
        intake.main()
    assert ei.value.code == 2
    assert "not PDF-compatible" in capsys.readouterr().out


def test_rerun_refuses_to_overwrite_hand_edited_draft(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    _blank_pdf(tmp_path / "deck.pdf")
    monkeypatch.setattr(intake, "ocr_pages", lambda *a, **k: ("", []))
    monkeypatch.setattr(intake.sys, "argv", ["intake.py", "deck.pdf", "--job", "Guard Job"])
    intake.main()
    draft = tmp_path / "booth_spec_Guard_Job_DRAFT.json"
    draft.write_text('{"hand": "edited"}')               # a designer confirmed things
    with pytest.raises(SystemExit) as ei:
        intake.main()
    assert ei.value.code == 1
    assert "--force" in capsys.readouterr().out
    assert draft.read_text(encoding="utf-8") == '{"hand": "edited"}'     # edit survived


def test_force_overwrites_existing_outputs(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _blank_pdf(tmp_path / "deck.pdf")
    monkeypatch.setattr(intake, "ocr_pages", lambda *a, **k: ("", []))
    monkeypatch.setattr(intake.sys, "argv", ["intake.py", "deck.pdf", "--job", "Guard Job"])
    intake.main()
    draft = tmp_path / "booth_spec_Guard_Job_DRAFT.json"
    draft.write_text('{"hand": "edited"}')
    monkeypatch.setattr(intake.sys, "argv",
                        ["intake.py", "deck.pdf", "--job", "Guard Job", "--force"])
    intake.main()                                        # no SystemExit
    assert json.loads(draft.read_text(encoding="utf-8")).get("_about")   # regenerated draft


def test_trailing_flag_without_value_exits_2_with_usage(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    _blank_pdf(tmp_path / "deck.pdf")
    monkeypatch.setattr(intake.sys, "argv", ["intake.py", "deck.pdf", "--job"])
    with pytest.raises(SystemExit) as ei:
        intake.main()                                    # argparse: no IndexError
    assert ei.value.code == 2
    assert "usage" in capsys.readouterr().err.lower()


def test_ai_field_guesses_maps_finish_and_finishing_type():
    ai = {"_status": "live", "panels": [
        {"name": "E", "finish": "fabric", "finishing_type": "SEG"},
        {"name": "K", "finish": "vinyl", "finishing_type": "TBD"},      # TBD value skipped
        {"name": "Z", "finish": "", "finishing_type": "Direct Print"},  # blank value skipped
    ]}
    panels = [{"name": "E"}, {"name": "K"}, {"name": "Z"}]
    assert intake.ai_field_guesses(ai, panels, "finish") == {"E": "fabric", "K": "vinyl"}
    assert intake.ai_field_guesses(ai, panels, "finishing_type") == {"E": "SEG", "Z": "Direct Print"}
    assert intake.ai_finish_guesses(ai, panels) == {"E": "fabric", "K": "vinyl"}   # wrapper
    assert intake.ai_field_guesses({"_status": "dry-run"}, panels, "finish") == {}
