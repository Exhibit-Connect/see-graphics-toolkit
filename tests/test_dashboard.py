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
