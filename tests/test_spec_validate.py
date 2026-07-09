"""P1-11: shared booth-JSON validation + escaped numeric-slot interpolations.

A broken hand-edited spec must produce ONE clear line per problem (naming the
panel/field) and exit nonzero BEFORE any client file is written — not a raw
KeyError halfway through a truncated HTML, and never raw markup injected into
a client-facing PDF.
"""
import json
import os
import sys

import pytest

import client_templates as ct
import generate_spec_packet as gsp
import preview_templates as pt
import spec_validate as sv


GOOD = {"job": {"name": "V"},
        "settings": {"bleed_per_side_in": 1.0, "safe_margin_in": 4.0, "scale": 0.5},
        "panels": [{"name": "F3", "w": 78.12, "h": 134.26,
                    "zones": [{"x": 0, "y": 0, "w": 10, "h": 10, "kind": "live"}]}]}


def _spec(**panel_over):
    p = dict(GOOD["panels"][0], **panel_over)
    return {"job": {"name": "V"}, "settings": dict(GOOD["settings"]), "panels": [p]}


# ---------- validate_spec (pure) ----------
def test_valid_spec_has_no_problems():
    assert sv.validate_spec(GOOD) == []


def test_missing_h_named_per_panel_and_field():
    spec = _spec()
    del spec["panels"][0]["h"]
    problems = sv.validate_spec(spec)
    assert problems == ["panel 'F3': missing 'h'"]


def test_string_w_is_a_clear_error_not_data():
    problems = sv.validate_spec(_spec(w="78"))
    assert len(problems) == 1
    assert "panel 'F3'" in problems[0] and "must be a number" in problems[0] and "'78'" in problems[0]


def test_scale_zero_rejected():
    spec = _spec()
    spec["settings"]["scale"] = 0
    problems = sv.validate_spec(spec)
    assert any("settings.scale" in p and "> 0" in p for p in problems)


def test_settings_numeric_strings_coerced_in_place():
    spec = _spec()
    spec["settings"]["bleed_per_side_in"] = "1.5"
    assert sv.validate_spec(spec) == []
    assert spec["settings"]["bleed_per_side_in"] == 1.5


def test_zone_missing_coordinate_geometry_mode():
    spec = _spec(zones=[{"w": 10, "h": 10, "kind": "keepclear", "label": "tv"}])
    problems = sv.validate_spec(spec)                    # zone_xy=True default
    assert any("missing 'x'" in p for p in problems)
    assert any("'tv'" in p for p in problems)            # zone named in the error


def test_label_only_keepclear_zone_ok_for_spec_packet():
    spec = _spec(zones=[{"label": "tv", "kind": "keepclear"}])
    assert sv.validate_spec(spec, zone_xy=False) == []   # intake drafts seed these
    # but a LIVE zone still needs printable w/h
    spec = _spec(zones=[{"label": "art", "kind": "live"}])
    problems = sv.validate_spec(spec, zone_xy=False)
    assert any("missing 'w'" in p for p in problems)


def test_top_level_array_reported_not_crash():
    problems = sv.validate_spec([1, 2, 3])
    assert problems and "JSON object" in problems[0]


def test_validate_or_raise_collects_all_problems():
    spec = _spec(w=None, h="x")
    spec["panels"][0].pop("w")
    with pytest.raises(sv.SpecError) as ei:
        sv.validate_or_raise(spec)
    assert len(ei.value.problems) == 2 + 0  # missing w + non-numeric h


# ---------- wiring: no partial output, exit 2, one line per problem ----------
def _write(tmp_path, spec):
    p = tmp_path / "booth_spec_v.json"
    p.write_text(json.dumps(spec))
    return str(p)


def test_client_templates_main_invalid_spec_exits_2_writes_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    spec = _spec()
    del spec["panels"][0]["h"]
    sp = _write(tmp_path, spec)
    monkeypatch.setattr(sys, "argv", ["client_templates.py", sp])
    with pytest.raises(SystemExit) as ei:
        ct.main()
    assert ei.value.code == 2
    assert "panel 'F3': missing 'h'" in capsys.readouterr().err
    assert not [f for f in os.listdir(tmp_path) if f.endswith(".html")]


def test_spec_packet_main_invalid_spec_exits_2_writes_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    sp = _write(tmp_path, _spec(w="78"))
    monkeypatch.setattr(sys, "argv", ["generate_spec_packet.py", sp])
    with pytest.raises(SystemExit) as ei:
        gsp.main()
    assert ei.value.code == 2
    assert "must be a number" in capsys.readouterr().err
    assert not list(tmp_path.glob("*Spec_Packet*")), "no partial HTML may be left"


def test_preview_main_invalid_spec_exits_2_writes_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    spec = _spec()
    spec["settings"]["scale"] = 0
    sp = _write(tmp_path, spec)
    monkeypatch.setattr(sys, "argv", ["preview_templates.py", sp])
    with pytest.raises(SystemExit) as ei:
        pt.main()
    assert ei.value.code == 2
    assert "settings.scale" in capsys.readouterr().err
    assert not list(tmp_path.glob("*.svg"))


def test_script_in_w_never_reaches_output_unescaped(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    sp = _write(tmp_path, _spec(w="<script>alert(1)</script>"))
    monkeypatch.setattr(sys, "argv", ["generate_spec_packet.py", sp])
    with pytest.raises(SystemExit):
        gsp.main()
    # rejected before render; and nothing on disk carries the raw tag
    for f in tmp_path.glob("*.html"):
        assert "<script>" not in f.read_text(encoding="utf-8")
    err = capsys.readouterr().err
    assert "&lt;script&gt;" in err or "<script>" in err  # named in the error is fine


def test_numeric_finish_renders_as_text_not_crash():
    spec = _spec(finish=5)
    doc = ct.build_templates_html(spec)                  # used to TypeError on escape
    assert ">5<" in doc or "5" in doc


def test_escaped_numeric_slots_in_spec_packet():
    # validated numbers still render; the slots go through esc()
    doc = gsp.build_html({"job": {"name": "V"}, "settings": dict(GOOD["settings"]),
                          "panels": [dict(GOOD["panels"][0])]})
    assert "78.12″ × 134.26″" in doc
    assert "Live art area:</b> 10″ × 10″" in doc


def test_excluded_entry_without_name_tolerated():
    spec = _spec()
    spec["excluded"] = [{"reason": "supplied by the venue"}]
    doc = gsp.build_html(spec)                           # used to KeyError at e['name']
    assert "supplied by the venue" in doc and "?" in doc
