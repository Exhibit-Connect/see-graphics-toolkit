"""P1-13: preview_templates — honest PNG fallback and small CLI fixes.

The qlmanage fallback force-fits a square canvas and has cropped wide booths;
a cropped PNG must be flagged, never silently presented as the booth. Plus:
strict-SVG-safe zone fills (fill-opacity, not 8-digit hex alpha) and a
bounds-checked --out.
"""
import json
import os
import re
import struct
import sys
import zlib

import pytest

import preview_templates as pt


SETTINGS = {"bleed_per_side_in": 1.0, "safe_margin_in": 4.0, "scale": 0.5}
SPEC = {"job": {"name": "P"}, "settings": SETTINGS,
        "panels": [{"name": "A", "w": 78.12, "h": 95.2,
                    "zones": [{"x": 0, "y": 0, "w": 20, "h": 20, "kind": "live"},
                              {"x": 30, "y": 0, "w": 20, "h": 20, "kind": "keepclear"}]}]}


# ---------- zone fill: strict-SVG-safe ----------
def test_zone_fill_uses_fill_opacity_not_8digit_hex():
    svg, _ = pt.build_svg(json.loads(json.dumps(SPEC)))
    assert 'fill-opacity="0.13"' in svg
    # no 8-digit hex color anywhere (invalid in strict SVG 1.1 viewers)
    assert not re.search(r'#[0-9A-Fa-f]{6}22"', svg)
    assert not re.search(r'"#[0-9A-Fa-f]{8}"', svg)


# ---------- --out bounds check ----------
def test_trailing_out_flag_exits_with_usage(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["preview_templates.py", "--out"])
    with pytest.raises(SystemExit) as ei:
        pt.main()
    assert ei.value.code == 2
    assert "usage" in capsys.readouterr().err


# ---------- PNG helpers ----------
def _write_png(path, w, h):
    """Minimal valid PNG (signature + IHDR + IDAT + IEND) at w x h."""
    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x00\x00\x00" * w for _ in range(h))
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def test_png_px_size_reads_ihdr(tmp_path):
    p = tmp_path / "x.png"
    _write_png(str(p), 320, 200)
    assert pt.png_px_size(str(p)) == (320, 200)
    (tmp_path / "not.png").write_bytes(b"nope")
    assert pt.png_px_size(str(tmp_path / "not.png")) is None


# ---------- qlmanage fallback honesty ----------
def _wide_svg(tmp_path):
    p = tmp_path / "wide.svg"
    p.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="400" '
                 'viewBox="0 0 1600 400"></svg>')
    return str(p)


def _fake_qlmanage(monkeypatch, out_w, out_h, rc=0):
    class _R:
        returncode = rc
        stderr = b""

    def fake_run(cmd, **kw):
        if rc == 0:
            td = cmd[cmd.index("-o") + 1]
            svg = cmd[-1]
            _write_png(os.path.join(td, os.path.basename(svg) + ".png"), out_w, out_h)
        return _R()

    monkeypatch.setattr(pt, "render_png", pt.render_png)  # ensure real function
    monkeypatch.setattr(pt.render, "svg_to_png", lambda *a, **k: False)  # no Chrome
    monkeypatch.setattr(pt.shutil, "which", lambda name: "/usr/bin/qlmanage")
    monkeypatch.setattr(pt.subprocess, "run", fake_run)


def test_qlmanage_square_output_for_wide_svg_flagged_cropped(tmp_path, monkeypatch, capsys):
    svg = _wide_svg(tmp_path)
    png = str(tmp_path / "out.png")
    _fake_qlmanage(monkeypatch, 800, 800)          # square: aspect 1 vs SVG's 4
    status = pt.render_png(svg, png)
    assert status == "qlmanage-cropped"
    assert "appears CROPPED" in capsys.readouterr().err
    assert os.path.exists(png)                     # the PNG is still there to inspect


def test_qlmanage_matching_aspect_passes_clean(tmp_path, monkeypatch, capsys):
    svg = _wide_svg(tmp_path)
    png = str(tmp_path / "out.png")
    _fake_qlmanage(monkeypatch, 1600, 400)
    assert pt.render_png(svg, png) == "qlmanage"
    assert "CROPPED" not in capsys.readouterr().err


def test_qlmanage_failure_returns_false_with_stderr_note(tmp_path, monkeypatch, capsys):
    svg = _wide_svg(tmp_path)
    png = str(tmp_path / "out.png")
    _fake_qlmanage(monkeypatch, 0, 0, rc=1)
    assert pt.render_png(svg, png) is False
    assert "qlmanage failed" in capsys.readouterr().err


def test_chrome_path_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(pt.render, "svg_to_png", lambda *a, **k: True)
    assert pt.render_png(str(tmp_path / "a.svg"), str(tmp_path / "a.png")) == "chrome"


def test_no_renderer_available_returns_false(tmp_path, monkeypatch):
    monkeypatch.setattr(pt.render, "svg_to_png", lambda *a, **k: False)
    monkeypatch.setattr(pt.shutil, "which", lambda name: None)
    assert pt.render_png(str(tmp_path / "a.svg"), str(tmp_path / "a.png")) is False


# ---------- main() messaging ----------
def test_main_cropped_png_message(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    sp = tmp_path / "booth_spec_p.json"
    sp.write_text(json.dumps(SPEC))
    monkeypatch.setattr(pt, "render_png", lambda *a, **k: "qlmanage-cropped")
    monkeypatch.setattr(sys, "argv", ["preview_templates.py", str(sp)])
    pt.main()
    assert "appears CROPPED, prefer the SVG" in capsys.readouterr().out


def test_main_total_failure_blames_both_paths(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    sp = tmp_path / "booth_spec_p.json"
    sp.write_text(json.dumps(SPEC))
    monkeypatch.setattr(pt, "render_png", lambda *a, **k: False)
    monkeypatch.setattr(sys, "argv", ["preview_templates.py", str(sp)])
    pt.main()
    out = capsys.readouterr().out
    assert "Chrome and qlmanage both unavailable or failed" in out
