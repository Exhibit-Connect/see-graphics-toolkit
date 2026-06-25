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
