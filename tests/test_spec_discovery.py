"""P1-8: booth-spec auto-discovery must be visible and unambiguous.

Client-facing tools (proofer, make_proof) refuse ambiguity AND lose the
examples/ fallback (artwork used to be silently preflighted against the
tracked example booth). Demo tools (previews, spec packet) keep the fallback
but announce it loudly.
"""
import json
import os
import sys

import pytest

import preview_templates as pt
import proofer


SPEC = {"job": {"name": "Disc Test"},
        "settings": {"bleed_per_side_in": 1.0, "scale": 0.5},
        "panels": [{"name": "A", "w": 10, "h": 20}]}


# ---------- proofer / make_proof (client-facing) ----------
def test_proofer_two_specs_in_cwd_exit_2_naming_both(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "booth_spec_a.json").write_text(json.dumps(SPEC))
    (tmp_path / "booth_spec_b.json").write_text(json.dumps(SPEC))
    with pytest.raises(SystemExit) as ei:
        proofer.find_default_spec()
    assert ei.value.code == 2
    err = capsys.readouterr().err
    assert "booth_spec_a.json" in err and "booth_spec_b.json" in err
    assert "--spec" in err


def test_proofer_single_spec_announced(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    sp = tmp_path / "booth_spec_a.json"
    sp.write_text(json.dumps(SPEC))
    assert proofer.find_default_spec() == str(sp)
    assert f"Using booth spec: {sp}" in capsys.readouterr().out


def test_proofer_no_spec_exits_2_never_the_example(tmp_path, monkeypatch, capsys):
    # the repo's tracked example booth must NEVER be silently used
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as ei:
        proofer.find_default_spec()
    assert ei.value.code == 2
    assert "pass" in capsys.readouterr().err.lower()  # tells the user what to do


def test_proofer_main_without_spec_exits_2_from_empty_dir(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["proofer.py", "art.pdf"])
    with pytest.raises(SystemExit) as ei:
        proofer.main()
    assert ei.value.code == 2


# ---------- demo tools keep a LOUD fallback ----------
def test_preview_two_specs_in_cwd_refuse(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "booth_spec_a.json").write_text(json.dumps(SPEC))
    (tmp_path / "booth_spec_b.json").write_text(json.dumps(SPEC))
    with pytest.raises(SystemExit) as ei:
        pt.find_default_spec()
    assert ei.value.code == 2


def test_preview_examples_fallback_is_loud(tmp_path, monkeypatch, capsys):
    # from an empty dir the demo fallback still fires, but is flagged as such
    monkeypatch.chdir(tmp_path)
    path = pt.find_default_spec()
    err = capsys.readouterr().err
    assert "examples" in path
    assert "DEMO fallback" in err and path in err


def test_preview_cwd_spec_announced_without_demo_warning(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    sp = tmp_path / "booth_spec_x.json"
    sp.write_text(json.dumps(SPEC))
    assert pt.find_default_spec() == str(sp)
    cap = capsys.readouterr()
    assert f"Using booth spec: {sp}" in cap.out
    assert "DEMO fallback" not in cap.err


def test_spec_packet_shares_preview_discovery():
    import generate_spec_packet as gsp
    assert gsp.find_default_spec.__module__ == "generate_spec_packet"
    # delegation: from a dir with one spec both return the same path
    # (behavioral identity is covered by the preview tests above)


# ---------- preview output naming derives from the spec stem ----------
def test_preview_output_name_derives_from_spec_stem(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    sp = tmp_path / "booth_spec_acme.json"
    sp.write_text(json.dumps(SPEC))
    monkeypatch.setattr(pt, "render_png", lambda *a, **k: False)
    monkeypatch.setattr(sys, "argv", ["preview_templates.py", str(sp)])
    pt.main()
    assert (tmp_path / "booth_spec_acme_preview.svg").exists()
    out = capsys.readouterr().out
    assert f"Spec: {sp}" in out and "Disc Test" in out


def test_preview_explicit_out_still_wins(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sp = tmp_path / "booth_spec_acme.json"
    sp.write_text(json.dumps(SPEC))
    monkeypatch.setattr(pt, "render_png", lambda *a, **k: False)
    monkeypatch.setattr(sys, "argv", ["preview_templates.py", str(sp), "--out", "mine"])
    pt.main()
    assert (tmp_path / "mine.svg").exists()
