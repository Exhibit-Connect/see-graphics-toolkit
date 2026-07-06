#!/usr/bin/env python3
"""
SEE Job Status Dashboard — every active job, at a glance.

Reads the booth files (the single source of truth) plus proof_log.xlsx and shows
one row per job: its STAGE (Intake -> Awaiting confirm -> In proof -> Approved),
the due date + days-to-due, and RISK FLAGS (panels still unverified, a failed
preflight, or an approaching deadline). Built only from data the toolkit already
produces, so it can't disagree with the other tools, and it degrades gracefully:
no proof log -> every job shows pre-proof; no due date -> the countdown is "—".

Usage:
    python3 tools/dashboard.py [--jobs-dir DIR] [--pdf]

Free / zero-install: pure-Python HTML, optional PDF via headless Chrome.
"""
import json, sys, os, glob, html, datetime
import proofer
import branding
import render

try:
    import openpyxl
except Exception:
    openpyxl = None

LOG = "proof_log.xlsx"
STAGE_COLORS = {"Intake": "#8a8a8a", "Awaiting confirm": "#F7941E",
                "Awaiting client artwork": "#7B61FF",
                "In proof": "#00AEEF", "Approved": "#2E9E40"}
DUE_SOON_DAYS = 3


# ---------- pure helpers (the tested core) ----------
def _blank(v):
    return v is None or str(v).strip() in ("", "—", "-")


def days_to_due(due_date, today):
    """Whole days from `today` (a date) until the due date; None if there's no
    usable date (TBD / blank / unparseable). Negative means overdue. Pure."""
    if due_date is None:
        return None
    if isinstance(due_date, (datetime.date, datetime.datetime)):
        d = due_date.date() if isinstance(due_date, datetime.datetime) else due_date
        return (d - today).days
    s = str(due_date).strip()
    if not s or s.upper() in ("TBD", "TBA", "—", "-", "N/A"):
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%B %d, %Y", "%b %d, %Y"):
        try:
            d = datetime.datetime.strptime(s, fmt).date()
            return (d - today).days
        except ValueError:
            continue
    return None


def latest_verdict(log_rows):
    """Most recent proof verdict from this job's log rows (file order = oldest
    first), or None if there are none. Pure."""
    for r in reversed(log_rows or []):
        v = r.get("Verdict")
        if v:
            return str(v)
    return None


def job_stage(spec, log_rows):
    """The job's workflow stage. An explicit job.status in the booth file WINS
    (lets a human set a stage we can't infer, e.g. 'Awaiting client artwork');
    otherwise infer from the proof log + the spec. Pure."""
    explicit = (spec.get("job", {}) or {}).get("status")
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    rows = log_rows or []
    if any(not _blank(r.get("Approved by")) for r in rows):
        return "Approved"
    if rows:
        return "In proof"
    if proofer.unverified_panels(spec):
        return "Awaiting confirm"
    return "Intake"


def job_risk_flags(spec, log_rows, today, due_soon_days=DUE_SOON_DAYS):
    """Plain-English risk flags for a job: unverified panels, a failed latest
    proof, and deadline pressure (an explicit approval_deadline takes priority
    over the due date). Empty list = on track. Pure."""
    flags = []
    unv = proofer.unverified_panels(spec)
    if unv:
        shown = ", ".join(unv[:6]) + ("…" if len(unv) > 6 else "")
        flags.append(f"{len(unv)} unverified panel(s): {shown}")
    if latest_verdict(log_rows) == "FAIL":
        flags.append("latest proof FAILS preflight")
    j = spec.get("job", {}) or {}
    dd = days_to_due(j.get("approval_deadline") or j.get("due_date"), today)
    if dd is not None:
        if dd < 0:
            flags.append(f"OVERDUE by {abs(dd)} day(s)")
        elif dd <= due_soon_days:
            flags.append(f"due in {dd} day(s)")
    return flags


def dashboard_rows(specs, log_index, today):
    """Build the dashboard table model (one dict per job) from a list of booth
    specs and a proof-log index {job_number: [row, ...]}. Sorted most-urgent
    first (soonest/overdue due date, dateless jobs last). Pure — no I/O."""
    rows = []
    for spec in specs:
        j = spec.get("job", {}) or {}
        job_no = j.get("job_number") or j.get("estimate") or ""
        logs = log_index.get(str(job_no), []) if job_no else []
        rows.append({
            "job_number": job_no or "—",
            "name": j.get("name") or j.get("client") or "—",
            "client": j.get("client") or "—",
            "show": j.get("show") or "—",
            "due_date": j.get("due_date") or "—",
            "days_to_due": days_to_due(j.get("due_date"), today),
            "stage": job_stage(spec, logs),
            "verdict": latest_verdict(logs),
            "flags": job_risk_flags(spec, logs, today),
        })
    rows.sort(key=lambda r: (r["days_to_due"] is None,
                             r["days_to_due"] if r["days_to_due"] is not None else 0))
    return rows


# ---------- discovery / proof-log reading (I/O) ----------
def discover_specs(jobs_dir=None):
    """Find every booth file to show. With --jobs-dir, scans it RECURSIVELY for
    *booth_spec*.json; otherwise looks in cwd and an examples/ folder (next to or
    above this script). Returns [(path, spec), ...], de-duped, bad files skipped."""
    here = os.path.dirname(os.path.abspath(__file__))
    paths = []
    if jobs_dir:
        paths = glob.glob(os.path.join(jobs_dir, "**", "*booth_spec*.json"), recursive=True)
    else:
        for d in (os.getcwd(), os.path.join(here, "..", "examples"),
                  os.path.join(os.getcwd(), "examples"), here):
            paths += glob.glob(os.path.join(d, "*booth_spec*.json"))
    out, seen = [], set()
    for p in sorted(paths):
        rp = os.path.realpath(p)
        if rp in seen:
            continue
        seen.add(rp)
        try:
            spec = json.load(open(p))
        except Exception:
            continue
        spec["__source"] = os.path.basename(p)
        out.append((p, spec))
    return out


def find_log():
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (LOG, os.path.join(os.getcwd(), LOG), os.path.join(here, "..", LOG)):
        if os.path.exists(p):
            return p
    return None


def read_proof_log(path=None):
    """Read proof_log.xlsx into {job_number: [row-dict, ...]} keyed by 'Job #'.
    Rows keep file order (oldest first). Returns {} when the log or openpyxl is
    missing — the dashboard then just shows every job pre-proof."""
    path = path or find_log()
    if not openpyxl or not path or not os.path.exists(path):
        return {}
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception:
        return {}
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return {}
    header = [str(h) if h is not None else "" for h in rows[0]]
    index = {}
    for r in rows[1:]:
        d = {header[i]: r[i] for i in range(min(len(header), len(r)))}
        key = str(d.get("Job #") or "")
        index.setdefault(key, []).append(d)
    return index


# ---------- report ----------
def _due_cell(row):
    dd = row["days_to_due"]
    base = html.escape(str(row["due_date"]))
    if dd is None:
        return base
    if dd < 0:
        return f'{base} <span class="od">({abs(dd)}d overdue)</span>'
    cls = "cd soon" if dd <= DUE_SOON_DAYS else "cd"
    return f'{base} <span class="{cls}">({dd}d)</span>'


def build_dashboard_html(rows, today=None):
    today = today or datetime.date.today()
    at_risk = sum(1 for r in rows if r["flags"])
    body = ""
    for r in rows:
        flags = ("".join(f'<span class="flag">{html.escape(f)}</span>' for f in r["flags"])
                 if r["flags"] else '<span class="ok">on track</span>')
        sc = STAGE_COLORS.get(r["stage"], "#6a6a6a")
        body += f"""<tr>
          <td class="jn">{html.escape(str(r['job_number']))}</td>
          <td><b>{html.escape(str(r['name']))}</b><br><span class="sub">{html.escape(str(r['client']))}</span></td>
          <td>{html.escape(str(r['show']))}</td>
          <td><span class="stage" style="background:{sc}">{html.escape(r['stage'])}</span></td>
          <td class="due">{_due_cell(r)}</td>
          <td class="flags">{flags}</td>
        </tr>"""
    if not rows:
        body = ('<tr><td colspan="6" class="empty">No booth files found. '
                'Point the dashboard at your jobs folder: '
                '<code>python3 tools/dashboard.py --jobs-dir /path/to/jobs</code></td></tr>')
    legend = "".join(
        f'<span class="lg"><span class="dot" style="background:{c}"></span>{html.escape(s)}</span>'
        for s, c in STAGE_COLORS.items())

    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
      @page {{ size: letter landscape; margin: 0.5in; }}
      * {{ box-sizing: border-box; }}
      body {{ font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; color:#1a1a1a; margin:0; }}
      h1 {{ font-size:24px; margin:8px 0 2px; }}
      .meta {{ color:#444; font-size:12px; margin-bottom:10px; }}
      .meta b {{ color:{branding.RED}; }}
      .legend {{ font-size:11px; color:#555; margin:6px 0 12px; }}
      .lg {{ margin-right:14px; white-space:nowrap; }}
      .dot {{ display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:5px; vertical-align:baseline; }}
      table {{ width:100%; border-collapse:collapse; font-size:12px; }}
      th {{ background:#f3f3f3; text-align:left; padding:7px 9px; border-bottom:2px solid #ccc; font-size:10.5px; text-transform:uppercase; letter-spacing:.02em; }}
      td {{ padding:8px 9px; border-bottom:1px solid #e8e8e8; vertical-align:top; }}
      td.jn {{ font-weight:700; white-space:nowrap; font-variant-numeric:tabular-nums; }}
      .sub {{ color:#888; font-size:10.5px; }}
      .stage {{ color:#fff; padding:3px 11px; border-radius:11px; font-weight:700; font-size:10.5px; white-space:nowrap; }}
      .due {{ white-space:nowrap; font-variant-numeric:tabular-nums; }}
      .od {{ color:#fff; background:{branding.RED}; padding:1px 7px; border-radius:9px; font-weight:700; font-size:10px; }}
      .cd {{ color:#888; font-size:10.5px; }}
      .cd.soon {{ color:{branding.RED}; font-weight:700; }}
      .flags {{ font-size:10.5px; }}
      .flag {{ display:inline-block; background:#fde8e8; color:#7a0d12; border:1px solid #f1b8b8; padding:2px 8px; border-radius:9px; margin:0 4px 4px 0; }}
      .ok {{ color:#2E9E40; font-weight:700; }}
      .empty {{ color:#888; text-align:center; padding:26px 9px; }}
      .empty code {{ background:#f3f3f3; padding:2px 6px; border-radius:5px; }}
      footer {{ margin-top:16px; color:#888; font-size:10px; border-top:1px solid #ddd; padding-top:6px; }}
      {branding.BRAND_CSS}
    </style></head><body>
      {branding.header_html("Job Status Dashboard")}
      <h1>Active jobs</h1>
      <div class="meta"><b>{len(rows)}</b> job(s) &nbsp;·&nbsp; <b>{at_risk}</b> with risk flag(s) &nbsp;·&nbsp; as of {today.strftime('%B %d, %Y')}</div>
      <div class="legend">Stage: {legend}</div>
      <table>
        <thead><tr><th>Job #</th><th>Job</th><th>Show</th><th>Stage</th><th>Due</th><th>Risk flags</th></tr></thead>
        <tbody>{body}</tbody>
      </table>
      <footer>Built from the booth files + proof_log.xlsx · Southeast Exhibits &amp; Events. Flags: unverified (AI/OCR) dimensions, a failed preflight, or an approaching due date.</footer>
    </body></html>"""


def main():
    args = sys.argv[1:]
    jobs_dir = None
    want_pdf = False
    i = 0
    while i < len(args):
        if args[i] == "--jobs-dir":
            jobs_dir = args[i + 1]; i += 2
        elif args[i] == "--pdf":
            want_pdf = True; i += 1
        else:
            i += 1
    today = datetime.date.today()
    specs = [s for _, s in discover_specs(jobs_dir)]
    log_index = read_proof_log()
    rows = dashboard_rows(specs, log_index, today)

    hp = os.path.abspath("job_dashboard.html")
    open(hp, "w").write(build_dashboard_html(rows, today))
    print(f"jobs: {len(rows)}  ·  at risk: {sum(1 for r in rows if r['flags'])}")
    for r in rows:
        flag = ("  ⚠ " + "; ".join(r["flags"])) if r["flags"] else ""
        print(f"  {str(r['job_number']):12} {r['stage']:18} {r['name']}{flag}")
    print("HTML:", hp)
    if want_pdf:
        pp = os.path.abspath("job_dashboard.pdf")
        if render.html_to_pdf(hp, pp):
            print("PDF :", pp)
        else:
            print("PDF step skipped — open the HTML and Print -> Save as PDF.")


if __name__ == "__main__":
    main()
