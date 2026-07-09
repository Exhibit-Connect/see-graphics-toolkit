"""Tests for the pure job-dashboard helpers in tools/dashboard.py.

Stage inference, due-date math, risk flags and the table model all work on
plain dicts (booth specs + a fake proof-log index), so no real xlsx, Chrome, or
filesystem is needed. `today` is pinned so the date math is deterministic.
"""
import datetime
import dashboard

TODAY = datetime.date(2026, 7, 1)


def test_days_to_due_formats_and_blanks():
    assert dashboard.days_to_due("2026-07-10", TODAY) == 9
    assert dashboard.days_to_due("2026-06-28", TODAY) == -3          # overdue
    assert dashboard.days_to_due("07/10/2026", TODAY) == 9           # US format
    assert dashboard.days_to_due("TBD", TODAY) is None
    assert dashboard.days_to_due("", TODAY) is None
    assert dashboard.days_to_due(None, TODAY) is None
    assert dashboard.days_to_due("not a date", TODAY) is None
    assert dashboard.days_to_due(datetime.date(2026, 7, 2), TODAY) == 1


def test_latest_verdict_takes_most_recent_row():
    rows = [{"Verdict": "FAIL"}, {"Verdict": "REVIEW"}, {"Verdict": "PASS"}]
    assert dashboard.latest_verdict(rows) == "PASS"
    assert dashboard.latest_verdict([]) is None
    assert dashboard.latest_verdict(None) is None


def test_job_stage_intake_when_nothing_else():
    spec = {"job": {"job_number": "J1"}, "panels": [{"name": "A", "w": 10, "h": 20}]}
    assert dashboard.job_stage(spec, []) == "Intake"


def test_job_stage_awaiting_confirm_on_needs_confirm():
    spec = {"job": {}, "panels": [{"name": "A", "w": 10, "h": 20, "needs_confirm": True}]}
    assert dashboard.job_stage(spec, []) == "Awaiting confirm"


def test_job_stage_in_proof_then_approved():
    spec = {"job": {}, "panels": [{"name": "A", "w": 10, "h": 20}]}
    assert dashboard.job_stage(spec, [{"Verdict": "REVIEW", "Approved by": None}]) == "In proof"
    assert dashboard.job_stage(spec, [{"Verdict": "PASS", "Approved by": "Jane Client"}]) == "Approved"


def test_job_stage_explicit_status_wins():
    # an explicit job.status overrides inference (covers 'Awaiting client artwork')
    spec = {"job": {"status": "Awaiting client artwork"},
            "panels": [{"name": "A", "w": 10, "h": 20, "needs_confirm": True}]}
    assert dashboard.job_stage(spec, [{"Verdict": "PASS", "Approved by": "X"}]) == "Awaiting client artwork"


def test_job_risk_flags_all_clear_is_empty():
    spec = {"job": {"due_date": "2026-09-01"}, "panels": [{"name": "A", "w": 10, "h": 20}]}
    assert dashboard.job_risk_flags(spec, [], TODAY) == []


def test_job_risk_flags_catches_unverified_fail_and_deadline():
    spec = {"job": {"due_date": "2026-07-02"},
            "panels": [{"name": "A", "w": 10, "h": 20, "needs_confirm": True}]}
    flags = dashboard.job_risk_flags(spec, [{"Verdict": "FAIL"}], TODAY)
    joined = " | ".join(flags)
    assert "unverified" in joined
    assert "FAIL" in joined
    assert "due in 1" in joined


def test_job_risk_flags_overdue_and_deadline_priority():
    # an explicit approval_deadline takes priority over due_date
    spec = {"job": {"due_date": "2026-09-01", "approval_deadline": "2026-06-29"},
            "panels": [{"name": "A", "w": 10, "h": 20}]}
    flags = dashboard.job_risk_flags(spec, [], TODAY)
    assert any("OVERDUE by 2" in f for f in flags)


# ---------- P1-5: honest stages, surfaced read failures, visible bad specs ----------
PANEL_SPEC = {"job": {}, "panels": [{"name": "A", "w": 10, "h": 20}]}


def test_job_stage_approval_then_fail_reproof_is_in_proof():
    rows = [{"Panel / Item": "A", "Verdict": "PASS", "Approved by": "Jane Client"},
            {"Panel / Item": "A", "Verdict": "FAIL", "Approved by": None}]
    assert dashboard.job_stage(PANEL_SPEC, rows) == "In proof"


def test_job_stage_partial_approval_is_not_approved():
    rows = [{"Panel / Item": "A", "Verdict": "PASS", "Approved by": "Jane Client"},
            {"Panel / Item": "B", "Verdict": "PASS", "Approved by": None}]
    stage = dashboard.job_stage(PANEL_SPEC, rows)
    assert stage != "Approved"
    assert stage == "Approved (1/2 items)"


def test_job_stage_all_panels_latest_approved_is_approved():
    rows = [{"Panel / Item": "A", "Verdict": "FAIL", "Approved by": None},   # old fail
            {"Panel / Item": "A", "Verdict": "PASS", "Approved by": "Jane"},
            {"Panel / Item": "B", "Verdict": "PASS", "Approved by": "Jane"}]
    assert dashboard.job_stage(PANEL_SPEC, rows) == "Approved"


def test_discover_specs_keeps_corrupt_file_visible(tmp_path, capsys):
    (tmp_path / "booth_spec_bad.json").write_text("{not json!!")
    (tmp_path / "booth_spec_ok.json").write_text('{"job": {"name": "Good"}, "panels": []}')
    found = dashboard.discover_specs(jobs_dir=str(tmp_path))
    assert len(found) == 2                                   # bad file did NOT vanish
    bad = [s for _, s in found if s.get("__unreadable")]
    assert len(bad) == 1 and bad[0]["__source"] == "booth_spec_bad.json"
    assert "could not be parsed" in capsys.readouterr().err
    rows = dashboard.dashboard_rows([s for _, s in found], {}, TODAY)
    unreadable = [r for r in rows if r["stage"] == "UNREADABLE"]
    assert len(unreadable) == 1
    assert any("could not be parsed" in f for f in unreadable[0]["flags"])


def test_discover_specs_top_level_array_no_crash(tmp_path, capsys):
    (tmp_path / "booth_spec_arr.json").write_text('[{"name": "A"}]')
    found = dashboard.discover_specs(jobs_dir=str(tmp_path))
    assert len(found) == 1 and found[0][1]["__unreadable"] is True
    assert "expected an object" in capsys.readouterr().err
    rows = dashboard.dashboard_rows([found[0][1]], {}, TODAY)  # no crash
    assert rows[0]["stage"] == "UNREADABLE"


def test_read_proof_log_openpyxl_missing_warning_reaches_html(monkeypatch):
    monkeypatch.setattr(dashboard, "openpyxl", None)
    index, warn = dashboard.read_proof_log("anything.xlsx")
    assert index == {}
    assert "openpyxl" in warn and "stages shown pre-proof" in warn
    doc = dashboard.build_dashboard_html([], TODAY, log_note=warn)
    assert "proof log NOT read" in doc or "stages shown pre-proof" in doc


def test_read_proof_log_missing_file_warns(tmp_path):
    index, warn = dashboard.read_proof_log(str(tmp_path / "nope.xlsx"))
    assert index == {} and "not found" in warn


def test_no_job_number_job_joins_log_rows_by_name():
    spec = {"job": {"name": "NoNum Job"}, "panels": [{"name": "A", "w": 10, "h": 20}]}
    log_index = {"": [{"Job": "NoNum Job", "Panel / Item": "A",
                       "Verdict": "REVIEW", "Approved by": None}]}
    rows = dashboard.dashboard_rows([spec], log_index, TODAY)
    assert rows[0]["stage"] == "In proof"                    # advanced past Intake
    assert rows[0]["verdict"] == "REVIEW"
    # a TBD job number (intake drafts) also uses the name join
    spec_tbd = {"job": {"name": "NoNum Job", "job_number": "TBD"},
                "panels": [{"name": "A", "w": 10, "h": 20}]}
    assert dashboard.dashboard_rows([spec_tbd], log_index, TODAY)[0]["stage"] == "In proof"


def test_dashboard_rows_stages_flags_and_urgency_sort():
    specs = [
        {"job": {"job_number": "J-LATE", "name": "Late Job", "due_date": "2026-07-03"},
         "panels": [{"name": "A", "w": 10, "h": 20}]},
        {"job": {"job_number": "J-NODATE", "name": "No Date Job", "due_date": "TBD"},
         "panels": [{"name": "B", "w": 10, "h": 20, "needs_confirm": True}]},
    ]
    log_index = {"J-LATE": [{"Verdict": "PASS", "Approved by": "Client A"}]}
    rows = dashboard.dashboard_rows(specs, log_index, TODAY)
    # dated job sorts before the date-less one
    assert rows[0]["job_number"] == "J-LATE"
    assert rows[0]["stage"] == "Approved"
    assert rows[0]["days_to_due"] == 2
    # the TBD job is pre-proof and flagged unverified
    nod = rows[1]
    assert nod["stage"] == "Awaiting confirm"
    assert nod["days_to_due"] is None
    assert any("unverified" in f for f in nod["flags"])
