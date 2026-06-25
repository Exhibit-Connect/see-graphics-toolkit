"""Tests for the pure, client-readiness helpers in tools/make_proof.py.

These cover the spec-block builder and the placeholder/blank guard that keeps
unfinished values (the proof-standardization memo's "TBD" / "Name here"
failures) from reaching a client. They operate on plain dicts - no PDF,
Ghostscript, Chrome, openpyxl, or network needed.
"""
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


def test_cover_rows_shapes_and_defaults():
    items = [
        {"panel": {"name": "F1", "w": 78.12, "h": 134.26, "finish": "Fabric", "sided": "single"}},
        {"panel": {"name": "A", "w": 50, "h": 100, "finish": "TBD", "sided": "double",
                   "quantity": 3, "tracking_id": "G-A"}},
    ]
    rows = mp.cover_rows(items)
    assert rows[0] == ("F1", '134.26" × 78.12"', "Fabric", "1", "1")    # qty + sides default
    assert rows[1] == ("G-A", '100" × 50"', "TBD", "2", "3")            # tracking_id + double
