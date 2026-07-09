"""Tests for the pure, client-readiness helpers in tools/make_proof.py.

These cover the spec-block builder and the placeholder/blank guard that keeps
unfinished values (the proof-standardization memo's "TBD" / "Name here"
failures) from reaching a client. They operate on plain dicts - no PDF,
Ghostscript, Chrome, openpyxl, or network needed.
"""
import os
import tempfile

import pytest

import make_proof as mp


def test_looks_placeholder_flags_unfinished_values():
    assert mp.looks_placeholder("TBD")
    assert mp.looks_placeholder("tbd")
    assert mp.looks_placeholder("Name here")
    assert mp.looks_placeholder("<finish>")
    assert mp.looks_placeholder("???")
    # real values are fine
    assert not mp.looks_placeholder("Fabric")
    assert not mp.looks_placeholder("Direct print")
    assert not mp.looks_placeholder("")
    assert not mp.looks_placeholder(None)


def test_is_blank():
    assert mp.is_blank(None)
    assert mp.is_blank("")
    assert mp.is_blank("   ")
    assert mp.is_blank("—")
    assert mp.is_blank("-")
    assert not mp.is_blank("Fabric")


def test_panel_specs_defaults_and_size_format():
    spec = {"job": {"version": "C3"}}
    panel = {"name": "F1", "w": 78.12, "h": 134.26, "finish": "Fabric", "sided": "single"}
    rows = dict(mp.panel_specs(panel, spec))
    assert rows["Item / tracking #"] == "F1"               # defaults to the panel name
    assert rows["Finish size (H × W)"] == '134.26" H × 78.12" W'
    assert rows["Material"] == "Fabric"
    assert rows["Finishing type"] == "—"                    # not provided -> dash
    assert rows["Quantity"] == "1"                          # default
    assert rows["Sides"] == "Single-sided"
    assert rows["Seams"] == "—"
    assert rows["Revision"] == "C3"                         # falls back to job version


def test_panel_specs_uses_explicit_optional_fields():
    spec = {"job": {"version": "C3"}}
    panel = {"name": "A", "w": 50, "h": 100, "finish": "Vinyl", "sided": "double",
             "finishing_type": "Direct print", "quantity": 2, "seams": "1",
             "tracking_id": "G-A", "rev": "B2"}
    rows = dict(mp.panel_specs(panel, spec))
    assert rows["Item / tracking #"] == "G-A"
    assert rows["Finishing type"] == "Direct print"
    assert rows["Quantity"] == "2"
    assert rows["Sides"] == "Double-sided"
    assert rows["Seams"] == "1"
    assert rows["Revision"] == "B2"


def test_proof_readiness_flags_placeholder_and_missing_names():
    spec = {"job": {"version": "C3"}}
    panel = {"name": "F1", "w": 78.12, "h": 134.26, "finish": "TBD", "sided": "single"}
    specs = mp.panel_specs(panel, spec)
    placeholders, missing = mp.proof_readiness(specs, None, None, panel["finish"])
    assert any("Material" in p for p in placeholders)       # 'TBD' material caught
    assert "Prepped by" in missing and "QC'd by" in missing


def test_proof_readiness_clean_when_complete():
    spec = {"job": {"version": "C3"}}
    panel = {"name": "F1", "w": 78.12, "h": 134.26, "finish": "Fabric", "sided": "single"}
    specs = mp.panel_specs(panel, spec)
    placeholders, missing = mp.proof_readiness(specs, "A. Tech", "M. Palumbo", panel["finish"])
    assert placeholders == []
    assert missing == []


def test_job_totals_counts_graphics_and_pieces():
    items = [{"panel": {"quantity": 2}}, {"panel": {"quantity": 1}}, {"panel": {}}]
    assert mp.job_totals(items) == (3, 4)          # 2 + 1 + default 1


# ---------- P0-11: job proof must disclose files it could not include ----------
JOB_PANEL = {"name": "F1", "w": 78, "h": 134, "finish": "Fabric"}
JOB_SPEC = {"job": {"name": "Booth Build", "client": "Acme Co", "job_number": "1001"},
            "settings": {}, "panels": [JOB_PANEL]}


def _canned_job_res():
    return {"panel": JOB_PANEL, "how": "matched from filename", "info": {"kind": "pdf"},
            "results": {"size": ("PASS", "ok"), "color": ("PASS", "CMYK")},
            "verdict": "PASS", "fixes": []}


def _job_items():
    res = _canned_job_res()
    return [{"panel": JOB_PANEL, "res": res, "specs": mp.panel_specs(JOB_PANEL, JOB_SPEC),
             "fname": "F1.pdf", "placeholders": [], "missing": [], "thumb_b64": ""}]


def test_build_job_html_discloses_unmatched_on_cover():
    doc = mp.build_job_html("Booth Build", JOB_SPEC, _job_items(), None, {},
                            unmatched=["wall_x.pdf (no matching panel)"])
    assert "NOT INCLUDED in this proof" in doc
    assert "wall_x.pdf" in doc and "no matching panel" in doc


def test_build_job_html_no_block_when_nothing_skipped():
    doc = mp.build_job_html("Booth Build", JOB_SPEC, _job_items(), None, {})
    assert "NOT INCLUDED" not in doc


def test_job_proof_with_unreadable_file_exits_nonzero(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    def fake_run_checks(path, spec, panel_arg=None):
        if "bad" in path:
            raise ValueError("unreadable artwork")
        return _canned_job_res()

    monkeypatch.setattr(mp.proofer, "run_checks", fake_run_checks)
    with pytest.raises(SystemExit) as ei:
        mp.build_job_proof(["bad.pdf", "F1.pdf"], JOB_SPEC, "Booth Build", "1001",
                           None, {}, None)
    assert ei.value.code == 1
    out = capsys.readouterr().out
    assert "NOT INCLUDED" in out and "--allow-skips" in out
    doc = open("Booth_Build_JOB_PROOF.html").read()   # document still produced
    assert "NOT INCLUDED in this proof" in doc and "bad.pdf" in doc
    assert "unreadable artwork" in doc                 # per-file reason disclosed


def test_job_proof_allow_skips_overrides_exit(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    def fake_run_checks(path, spec, panel_arg=None):
        if "bad" in path:
            raise ValueError("unreadable artwork")
        return _canned_job_res()

    monkeypatch.setattr(mp.proofer, "run_checks", fake_run_checks)
    mp.build_job_proof(["bad.pdf", "F1.pdf"], JOB_SPEC, "Booth Build", "1001",
                       None, {}, None, allow_skips=True)   # no SystemExit
    assert "NOT INCLUDED" in capsys.readouterr().out


def test_job_proof_clean_run_has_no_skip_block_or_exit(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mp.proofer, "run_checks",
                        lambda *a, **k: _canned_job_res())
    mp.build_job_proof(["F1.pdf", "F1_b.pdf"], JOB_SPEC, "Booth Build", "1001",
                       None, {}, None)
    assert "NOT INCLUDED" not in open("Booth_Build_JOB_PROOF.html").read()


def test_job_proof_all_files_skipped_exits_nonzero(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mp.proofer, "run_checks", lambda *a, **k: None)  # no panel match
    with pytest.raises(SystemExit) as ei:
        mp.build_job_proof(["x.pdf", "y.pdf"], JOB_SPEC, "Booth Build", "1001",
                           None, {}, None)
    assert ei.value.code == 2
    assert "no files matched" in capsys.readouterr().out


# ---------- P0-10: thumbnails must never embed a stale/wrong image ----------
class _R:
    def __init__(self, rc):
        self.returncode = rc


def test_thumbnail_gs_failure_returns_none_never_the_stale_decoy(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    decoy = tmp_path / "_proof_thumb.png"           # the old fixed cwd path
    decoy.write_bytes(b"stale image from another job")
    monkeypatch.setattr(mp.subprocess, "run", lambda *a, **k: _R(1))
    assert mp.thumbnail(str(tmp_path / "art.pdf"), ".pdf") is None
    assert decoy.read_bytes() == b"stale image from another job"  # untouched, never returned


def test_thumbnail_gs_rc0_but_no_output_returns_none(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mp.subprocess, "run", lambda *a, **k: _R(0))  # writes nothing
    assert mp.thumbnail(str(tmp_path / "art.pdf"), ".pdf") is None


def test_thumbnail_success_yields_unique_fresh_temp_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def fake_run(cmd, **kw):
        out = cmd[cmd.index("-o") + 1]
        with open(out, "wb") as f:
            f.write(b"\x89PNG fresh render")
        return _R(0)

    monkeypatch.setattr(mp.subprocess, "run", fake_run)
    a = mp.thumbnail("art.pdf", ".pdf")
    b = mp.thumbnail("art.pdf", ".pdf")
    try:
        assert a and b and a != b                        # unique per run
        assert os.path.basename(a) != "_proof_thumb.png"  # not the old fixed name
        assert open(a, "rb").read() == b"\x89PNG fresh render"
    finally:
        for p in (a, b):
            if p and os.path.exists(p):
                os.remove(p)


def test_single_proof_cleans_thumb_even_when_build_fails(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    res = {"panel": {"name": "F1", "w": 78, "h": 134, "finish": "Fabric"},
           "how": "named explicitly", "info": {"kind": "pdf"},
           "results": {"size": ("PASS", "ok")}, "verdict": "PASS", "fixes": []}
    monkeypatch.setattr(mp.proofer, "run_checks", lambda *a, **k: res)
    created = []

    def fake_thumb(path, ext, tag=""):
        fd, out = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        created.append(out)
        return out

    monkeypatch.setattr(mp, "thumbnail", fake_thumb)

    def boom(*a, **k):
        raise RuntimeError("render blew up")

    monkeypatch.setattr(mp, "build_proof_html", boom)
    with pytest.raises(RuntimeError):
        mp.build_single_proof("F1.pdf", {"panels": [res["panel"]]}, "Job", None,
                              None, {}, None)
    assert created and not os.path.exists(created[0])   # cleaned up in finally


# ---------- P0-6: explicit --panel that matches nothing must error out ----------
def test_build_single_proof_explicit_panel_not_found_exits(tmp_path, capsys):
    spec = {"settings": {}, "panels": [{"name": "Wall A", "w": 10, "h": 20}]}
    with pytest.raises(SystemExit) as ei:
        mp.build_single_proof(str(tmp_path / "art.pdf"), spec, "Job", None,
                              None, {}, "Wall_Z")
    assert ei.value.code == 2
    out = capsys.readouterr().out
    assert 'no panel named "Wall_Z"' in out and "Wall A" in out


def test_cover_rows_shapes_and_defaults():
    items = [
        {"panel": {"name": "F1", "w": 78.12, "h": 134.26, "finish": "Fabric", "sided": "single"}},
        {"panel": {"name": "A", "w": 50, "h": 100, "finish": "TBD", "sided": "double",
                   "quantity": 3, "tracking_id": "G-A"}},
    ]
    rows = mp.cover_rows(items)
    assert rows[0] == ("F1", '134.26" × 78.12"', "Fabric", "1", "1")    # qty + sides default
    assert rows[1] == ("G-A", '100" × 50"', "TBD", "2", "3")            # tracking_id + double
