#!/usr/bin/env python3
"""
SEE Proof + Sign-off (Phase 4) - proofing we own, not the vendor's.

From a client's artwork + the booth spec, builds a branded PROOF that follows
SEE's unified proof standard (per Production's proof-standardization memo).

Two modes:
  * SINGLE ITEM (one artwork file): a one-page proof - artwork + a structured
    SPEC block + the automated preflight results (with a status legend) + a
    prominent disclaimer banner + a 3-option client sign-off + a consistent
    footer (prepped/QC/job#/version/fulfillment/page).
  * WHOLE JOB (several artwork files, or a folder, or --book): ONE multi-page
    PDF = a COVER/SUMMARY page (logo + job info + a table of every item +
    review instructions) followed by one page per item, with real Page X of Y.

Every proof is logged to proof_log.xlsx. Approve a single item to stamp + lock
the record; it refuses to approve a FAIL, or anything still carrying a
placeholder/blank value (no "TBD" or "Name here" reaches a client).

Usage:
    # one item
    python3 make_proof.py <artwork> [--spec booth_spec.json] [--panel NAME]
        [--job "Name"] [--prepped-by "Name"] [--qc-by "Name"]
        [--version V] [--fulfillment delivery|pickup] [--approve "Client Name"]
        [--ack-review "reason"]   # required to approve a NEEDS-REVIEW proof; recorded
    # whole job (assembled document)
    python3 make_proof.py <art1> <art2> ...           # or a folder, or --book
        [--spec ...] [--prepped-by N] [--qc-by N] [--version V] [--fulfillment ...]
"""
import sys, os, re, json, glob, base64, subprocess, datetime, html, functools
import proofer
try:
    import openpyxl
except Exception:
    openpyxl = None

RED = proofer.branding.RED
LOG = "proof_log.xlsx"
VCOL = {"PASS": "#2E9E40", "REVIEW": "#F7941E", "FAIL": RED}
VLABEL = {"PASS": "PASS", "REVIEW": "NEEDS REVIEW", "FAIL": "FAIL"}
CONTACT = ("Southeast Exhibits &amp; Events &nbsp;·&nbsp; Orlando | Las Vegas | Atlanta | NJ/NY | Dallas "
           "&nbsp;·&nbsp; SouthEastExhibit.com")
DISCLAIMER = ("This proof is for verifying CONTENT, LAYOUT, COLOR BREAK and SIZE only. On-screen color is "
              "not an exact match to the final printed piece. Check spelling, dimensions and finish "
              "carefully — your approval releases this file to print.")
ART_EXT = (".pdf", ".ai", ".eps") + proofer.RASTER_EXT

# literal placeholder / unfilled markers that must never reach a client
# (deliberately NOT 'n/a' - that is a legitimate value)
PLACEHOLDER_RE = re.compile(
    r"\b(tbd|tba|todo|name here|placeholder|lorem|xxx+|fpo|tk|fill ?in|change ?me|"
    r"client name|your (?:name|logo|text))\b|[<>]|\?\?\?", re.I)


def looks_placeholder(v):
    """True if a value carries literal placeholder/markup text (the memo's
    'no placeholder reaches the client' failure, e.g. 'TBD', 'Name here')."""
    return bool(v) and bool(PLACEHOLDER_RE.search(str(v)))


def is_blank(v):
    """True if a value is effectively empty (None / '' / a bare dash)."""
    return v is None or str(v).strip() in ("", "—", "-")


def panel_specs(panel, spec, version=None):
    """Ordered (label, value) rows for the client-facing spec block - the fields
    SEE's proof standard requires, pulled from the single-source booth spec.
    Optional fields (finishing_type / quantity / seams / tracking_id / rev) are
    read from the panel when present, else a sensible default or '—'. Pure."""
    w, h = panel.get("w"), panel.get("h")
    finish_size = f'{h:g}" H × {w:g}" W' if (w and h) else "—"
    sided = str(panel.get("sided", "")).strip().lower()
    sided_label = {"single": "Single-sided", "double": "Double-sided"}.get(sided, panel.get("sided") or "—")
    seams = panel.get("seams")
    rev = panel.get("rev") or version or spec.get("job", {}).get("version") or "—"
    return [
        ("Item / tracking #", panel.get("tracking_id") or panel.get("name") or "—"),
        ("Finish size (H × W)", finish_size),
        ("Material", panel.get("finish") or "—"),
        ("Finishing type", panel.get("finishing_type") or "—"),
        ("Quantity", str(panel.get("quantity", 1))),
        ("Sides", sided_label),
        ("Seams", "—" if seams in (None, "") else str(seams)),
        ("Revision", str(rev)),
    ]


def proof_readiness(specs, prepped_by, qc_by, material):
    """Client-readiness gate (the memo's 'no placeholder reaches the client' rule
    + 'QC/Prepped by = an actual name, never a placeholder'). Returns
    (placeholders, missing):
      placeholders - values carrying literal placeholder text; must NEVER ship.
      missing      - required fields (Prepped by, QC'd by, Material) not yet set.
    Blank OPTIONAL spec fields (finishing type / seams) are not 'missing' here -
    the caller surfaces those as a soft note. Pure function."""
    placeholders, missing = [], []
    for label, val in specs:
        if looks_placeholder(val):
            placeholders.append(f"{label} = '{val}'")
    for label, val in (("Prepped by", prepped_by), ("QC'd by", qc_by)):
        if is_blank(val):
            missing.append(label)
        elif looks_placeholder(val):
            placeholders.append(f"{label} = '{val}'")
    if is_blank(material):
        missing.append("Material")
    return placeholders, missing


def job_readiness(spec, job=None, version=None):
    """Placeholder scan over the JOB-level fields that render on client proofs
    (job name, client, show, job #, version) - these used to bypass the
    per-panel placeholder gate. Returns the same \"Label = 'value'\" strings
    proof_readiness produces, so callers can merge the two lists. Pure."""
    j = spec.get("job", {})
    fields = [("Job name", job if job is not None else j.get("name")),
              ("Client", j.get("client")),
              ("Show", j.get("show")),
              ("Job #", j.get("job_number")),
              ("Proof version", version if version is not None else j.get("version"))]
    return [f"{label} = '{val}'" for label, val in fields if looks_placeholder(val)]


def job_totals(items):
    """(# graphics, # pieces) for the cover - graphics = number of items,
    pieces = sum of each item's quantity (default 1). Pure function."""
    pieces = 0
    for it in items:
        q = it["panel"].get("quantity", 1)
        try:
            pieces += int(q)
        except (TypeError, ValueError):
            pieces += 1
    return len(items), pieces


def cover_rows(items):
    """Per-item rows for the cover summary table: (item, size, material, sides,
    qty). Pure function."""
    rows = []
    for it in items:
        p = it["panel"]
        w, h = p.get("w"), p.get("h")
        size = f'{h:g}" × {w:g}"' if (w and h) else "—"
        sided = str(p.get("sided", "")).strip().lower()
        sides = {"single": "1", "double": "2"}.get(sided, str(p.get("sided") or "—"))
        rows.append((p.get("tracking_id") or p.get("name") or "—", size,
                     p.get("finish") or "—", sides, str(p.get("quantity", 1))))
    return rows


def thumbnail(path, ext, tag=""):
    out = os.path.abspath(f"_proof_thumb{tag}.png")
    try:
        if ext in proofer.RASTER_EXT:
            from PIL import Image
            im = Image.open(path)
            if im.mode == "CMYK":
                im = im.convert("RGB")
            im.thumbnail((1000, 1000))
            im.save(out)
        else:
            subprocess.run(["gs", "-q", "-sDEVICE=png16m", "-r60", "-dFirstPage=1",
                            "-dLastPage=1", "-o", out, path], capture_output=True)
        return out if os.path.exists(out) else None
    except Exception:
        return None


def b64img(p):
    return "data:image/png;base64," + base64.b64encode(open(p, "rb").read()).decode() if p else ""


@functools.lru_cache(maxsize=1)
def _logo_data_uri():
    """Find the SEE logo PNG and return it as a data URI, else '' (the proof
    falls back to a text wordmark). Looks in assets/ next to the tools/ dir, the
    repo root, and cwd - so it works regardless of where the tool is run."""
    here = os.path.dirname(os.path.abspath(__file__))
    seen = []
    for d in (os.path.join(here, "..", "assets"), os.path.join(os.getcwd(), "assets"),
              here, os.path.join(here, ".."), os.getcwd()):
        seen += sorted(glob.glob(os.path.join(d, "see_logo.png")))
        seen += sorted(glob.glob(os.path.join(d, "*[Ll]ogo*.png")))
    for p in seen:
        try:
            return "data:image/png;base64," + base64.b64encode(open(p, "rb").read()).decode()
        except OSError:
            continue
    return ""


def log_proof(job, job_no, panel, fname, verdict, status, version, prepped, qc, approver):
    if not openpyxl:
        return "(openpyxl missing - log skipped)"
    header = ["Date", "Job", "Job #", "Panel / Item", "File", "Verdict", "Status",
              "Proof version", "Prepped by", "QC'd by", "Approved by"]
    if os.path.exists(LOG):
        wb = openpyxl.load_workbook(LOG); ws = wb.active
    else:
        wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Proofs"
        ws.append(header)
    ws.append([datetime.date.today().isoformat(), job, job_no or "", panel,
               os.path.basename(fname), verdict, status, version or "",
               prepped or "", qc or "", approver or ""])
    wb.save(LOG)
    return LOG


CSS_PROOF = """
  @page { size: letter portrait; margin: 0.5in; }
  body { font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; color:#1a1a1a; font-size:12px; margin:0; }
  .page { page-break-after: always; }
  .page:last-child { page-break-after: auto; }
  .pill { background:#E31D3D; color:#fff; display:inline-block; padding:5px 14px; border-radius:16px; font-weight:700; font-size:11px; }
  h1 { font-size:19px; margin:9px 0 1px; }
  .meta { color:#555; font-size:11px; margin:1px 0 0; }
  .verdict { display:inline-block; color:#fff; padding:4px 12px; border-radius:7px; font-weight:700; font-size:13px; }
  .legend { font-size:10px; color:#666; margin-left:8px; }
  .legend .dot { display:inline-block; width:9px; height:9px; border-radius:50%; margin:0 3px 0 9px; vertical-align:baseline; }
  .banner { margin:11px 0; padding:9px 13px; background:#FFF4E5; border:1px solid #F7941E; border-left:6px solid #F7941E;
            border-radius:5px; color:#7a4a00; font-size:11px; font-weight:600; line-height:1.35; }
  .caution { margin:11px 0; padding:9px 13px; background:#fde8e8; border:1px solid #E31D3D; border-left:6px solid #E31D3D;
             border-radius:5px; color:#7a0d12; font-size:11px; font-weight:700; line-height:1.35; }
  .cols { display:flex; gap:15px; margin-top:6px; }
  .art { flex:0 0 40%; border:1px solid #ddd; border-radius:6px; padding:6px; text-align:center; background:#fafafa; align-self:flex-start; }
  .art img { max-width:100%; max-height:330px; }
  .noimg { color:#999; padding:40px 0; }
  .right { flex:1; }
  .blk { font-size:10px; text-transform:uppercase; letter-spacing:.04em; color:#888; font-weight:700; margin:0 0 4px; }
  table { width:100%; border-collapse:collapse; }
  table.spec { margin-bottom:13px; }
  table.spec td { padding:4px 8px; border-bottom:1px solid #eee; font-size:11px; vertical-align:top; }
  td.sl { color:#666; width:42%; }
  td.sv { font-weight:700; }
  table.chk th { background:#f3f3f3; text-align:left; padding:5px 8px; border-bottom:2px solid #ccc; font-size:9.5px; text-transform:uppercase; }
  table.chk td { padding:5px 8px; border-bottom:1px solid #ececec; vertical-align:top; }
  td.ck { font-weight:700; width:20%; }
  .b { color:#fff; padding:2px 9px; border-radius:10px; font-weight:700; font-size:9.5px; }
  .msg { font-size:10px; }
  ol.fixlist { margin:7px 0 0; padding-left:18px; }
  ol.fixlist li { font-size:10px; margin:3px 0; color:#7a4a00; }
  .signbox { margin-top:14px; border:1.5px solid #bbb; border-radius:8px; padding:11px 14px; }
  .sign .st { font-weight:700; color:#E31D3D; margin-bottom:7px; }
  .sign .opt { margin-bottom:5px; font-size:12px; }
  .sign .lines { margin:11px 0 9px; }
  .sign .chg { color:#555; }
  .stamp { display:inline-block; border:3px solid #2E9E40; color:#2E9E40; font-weight:800; font-size:17px; padding:7px 16px; border-radius:8px; letter-spacing:.04em; }
  .locknote { color:#7a0d12; font-size:11px; margin-top:8px; }
  footer { margin-top:14px; border-top:1px solid #ddd; padding-top:7px; }
  .ftgrid { display:flex; flex-wrap:wrap; gap:6px 18px; font-size:10px; }
  .ftgrid div span { display:block; text-transform:uppercase; letter-spacing:.03em; color:#999; font-size:8.5px; font-weight:700; }
  .ftgrid div b { font-size:11px; }
  .contact { color:#999; font-size:9px; margin-top:7px; }
  /* cover */
  .brandrow { display:flex; justify-content:space-between; align-items:center; }
  .wordmark { font-size:18px; font-weight:800; color:#E31D3D; letter-spacing:.01em; }
  .logo { height:56px; width:auto; display:block; margin-bottom:4px; }
  .logosm { height:30px; width:auto; }
  .phead { display:flex; justify-content:space-between; align-items:center; }
  .coverhead { color:#999; font-size:9px; margin-top:2px; }
  h1.cv { font-size:23px; margin:16px 0 2px; }
  .jobgrid { display:flex; flex-wrap:wrap; gap:7px 26px; margin:10px 0 4px; }
  .jobgrid div span { display:block; text-transform:uppercase; letter-spacing:.03em; color:#999; font-size:8.5px; font-weight:700; }
  .jobgrid div b { font-size:12.5px; }
  .totals { margin:14px 0 6px; font-size:13px; }
  .totals b { color:#E31D3D; }
  table.summary th { background:#E31D3D; color:#fff; text-align:left; padding:7px 9px; font-size:10px; text-transform:uppercase; }
  table.summary td { padding:6px 9px; border-bottom:1px solid #eaeaea; font-size:11px; }
  table.summary tr:nth-child(even) td { background:#fafafa; }
  table.summary .muted { color:#c0392b; font-weight:700; }
  .howto { margin-top:15px; border:1px solid #ddd; border-radius:7px; padding:11px 14px; background:#f7f9fb; font-size:11px; line-height:1.5; }
  .howto b { color:#E31D3D; }
"""

HEAD = '<!doctype html><html><head><meta charset="utf-8"><style>' + CSS_PROOF + '</style></head><body>'
FOOT = '</body></html>'


def _item_footer(meta, today, job_no):
    version = meta.get("version") or "—"
    prepped = meta.get("prepped_by") or "—"
    qc = meta.get("qc_by") or "—"
    fulfillment = (meta.get("fulfillment") or "").title() or "—"
    page, pages = meta.get("page", 1), meta.get("pages", 1)
    return f"""<footer>
        <div class="ftgrid">
          <div><span>Prepped by</span><b>{html.escape(str(prepped))}</b></div>
          <div><span>QC'd by</span><b>{html.escape(str(qc))}</b></div>
          <div><span>Date issued</span><b>{today}</b></div>
          <div><span>Job #</span><b>{html.escape(str(job_no))}</b></div>
          <div><span>Proof version</span><b>{html.escape(str(version))}</b></div>
          <div><span>Fulfillment</span><b>{html.escape(str(fulfillment))}</b></div>
          <div><span>Page</span><b>{page} of {pages}</b></div>
        </div>
        <div class="contact">{CONTACT}</div>
      </footer>"""


def _item_body(job, res, spec, thumb_b64, approve, meta, logo=""):
    """One item's page (no <html>/<body> wrapper) - a <section class='page'>.
    `logo` (a data URI) shows a small mark in the header for a standalone proof;
    in the job document the cover carries the logo, so item pages pass ''."""
    today = datetime.date.today().strftime("%B %d, %Y")
    verdict = res["verdict"]
    panel = res["panel"]
    specs = meta["specs"]
    job_no = spec.get("job", {}).get("job_number") or spec.get("job", {}).get("estimate") or "—"
    version = meta.get("version") or "—"

    spec_rows = "".join(
        f'<tr><td class="sl">{html.escape(l)}</td><td class="sv">{html.escape(str(v))}</td></tr>'
        for l, v in specs)
    chk_rows = ""
    for k in proofer.ORDER:
        if k in res["results"]:
            st, msg = res["results"][k]
            chk_rows += (f'<tr><td class="ck">{k.title()}</td>'
                         f'<td><span class="b" style="background:{proofer.BADGE[st]}">{st}</span></td>'
                         f'<td class="msg">{html.escape(msg)}</td></tr>')
    fixes = res.get("fixes") or []
    fix_block = ""
    if fixes:
        flis = "".join(f'<li><b>{html.escape(f["check"].title())}:</b> {html.escape(f["text"])}</li>'
                       for f in fixes)
        fix_block = f'<div class="blk">What to change</div><ol class="fixlist">{flis}</ol>'
    if approve:
        ack = meta.get("ack_review")
        ack_html = (f'<div class="locknote">NEEDS-REVIEW items acknowledged before approval — '
                    f'reason: {html.escape(str(ack))}</div>' if ack else '')
        signoff = (f'<div class="stamp">APPROVED &nbsp;·&nbsp; {html.escape(approve)} &nbsp;·&nbsp; {today}</div>'
                   f'{ack_html}'
                   f'<div class="locknote">Locked on approval. Any change after this requires written approval '
                   f'and may trigger an add-on charge.</div>')
    else:
        signoff = (
            '<div class="sign"><div class="st">Client approval</div>'
            '<div class="opt">&#9744;&nbsp; Approved as is</div>'
            '<div class="opt">&#9744;&nbsp; Approved with changes noted below</div>'
            '<div class="opt">&#9744;&nbsp; Revisions required — please resubmit for approval</div>'
            '<div class="lines">Signature ____________________________ &nbsp; Printed name ____________________ &nbsp; Date __________</div>'
            '<div class="chg">Notes / changes: _______________________________________________________________________</div></div>')
    img = f'<img src="{thumb_b64}">' if thumb_b64 else '<div class="noimg">(preview unavailable)</div>'
    caution = ""
    if not approve and (meta.get("placeholders") or meta.get("missing")):
        items = "; ".join(meta["placeholders"] + [f"{m} not set" for m in meta["missing"]])
        caution = (f'<div class="caution">&#9888; DRAFT — not client-ready: {html.escape(items)}. '
                   f'Resolve before sending to the client.</div>')

    logo_html = f'<img class="logosm" src="{logo}">' if logo else ''
    return f"""<section class="page">
      <div class="phead"><div class="pill">Artwork Proof — for client approval</div>{logo_html}</div>
      <h1>{html.escape(job)} &nbsp;—&nbsp; Item {html.escape(panel['name'])}</h1>
      <div class="meta">Proof version {html.escape(str(version))} &nbsp;·&nbsp; {today} &nbsp;·&nbsp; checked against the booth spec &nbsp;·&nbsp;
        <span class="verdict" style="background:{VCOL[verdict]}">{VLABEL[verdict]}</span>
        <span class="legend">
          <span class="dot" style="background:#2E9E40"></span>Pass
          <span class="dot" style="background:#F7941E"></span>Needs review
          <span class="dot" style="background:#E31D3D"></span>Fail</span>
      </div>
      <div class="banner">{DISCLAIMER}</div>
      {caution}
      <div class="cols">
        <div class="art">{img}</div>
        <div class="right">
          <div class="blk">Specifications</div>
          <table class="spec">{spec_rows}</table>
          <div class="blk">Automated preflight checks</div>
          <table class="chk"><thead><tr><th>Check</th><th>Result</th><th>Detail</th></tr></thead><tbody>{chk_rows}</tbody></table>
          {fix_block}
        </div>
      </div>
      <div class="signbox">{signoff}</div>
      {_item_footer(meta, today, job_no)}
    </section>"""


def build_proof_html(job, res, spec, thumb_b64, approve, meta):
    """Single-item proof (full HTML document)."""
    return HEAD + _item_body(job, res, spec, thumb_b64, approve, meta, logo=_logo_data_uri()) + FOOT


def _cover_body(job, spec, items, meta):
    """The job COVER / summary page (a <section class='page'>)."""
    today = datetime.date.today().strftime("%B %d, %Y")
    logo = _logo_data_uri()
    brand = (f'<img class="logo" src="{logo}">' if logo
             else '<div class="wordmark">Southeast Exhibits &amp; Events</div>')
    j = spec.get("job", {})
    job_no = j.get("job_number") or j.get("estimate") or "—"
    version = meta.get("version") or j.get("version") or "—"
    due = j.get("due_date")
    due_txt = "" if (is_blank(due) or looks_placeholder(due)) else f" Please return the signed proof by <b>{html.escape(str(due))}</b>."
    n_graphics, n_pieces = job_totals(items)

    fields = [("Client", j.get("client")), ("Show", j.get("show")), ("Booth", j.get("booth_size")),
              ("Job #", job_no), ("Proof version", version), ("Date issued", today)]
    jobgrid = "".join(f'<div><span>{html.escape(l)}</span><b>{html.escape(str(v or "—"))}</b></div>'
                      for l, v in fields)

    srows = ""
    for i, (name, size, material, sides, qty) in enumerate(cover_rows(items), 1):
        mcls = ' class="muted"' if looks_placeholder(material) else ""
        srows += (f'<tr><td>{i}</td><td><b>{html.escape(name)}</b></td><td>{html.escape(size)}</td>'
                  f'<td{mcls}>{html.escape(material)}</td><td>{html.escape(sides)}</td><td>{html.escape(qty)}</td></tr>')

    return f"""<section class="page cover">
      <div class="brandrow">
        <div>{brand}
          <div class="coverhead">Orlando | Las Vegas | Atlanta | NJ/NY | Dallas &nbsp;·&nbsp; SouthEastExhibit.com</div></div>
        <div class="pill">Client Proof</div>
      </div>
      <h1 class="cv">{html.escape(job)}</h1>
      <div class="jobgrid">{jobgrid}</div>
      <div class="totals">This proof covers <b>{n_graphics}</b> graphic(s) — <b>{n_pieces}</b> piece(s) total.</div>
      <table class="summary"><thead><tr><th>#</th><th>Item</th><th>Finish size (H × W)</th><th>Material</th><th>Sides</th><th>Qty</th></tr></thead>
        <tbody>{srows}</tbody></table>
      <div class="howto"><b>How to review:</b> Each graphic is on its own page that follows. For every item,
        check the artwork, spelling, dimensions and finish, then mark one box — <b>Approved as is</b>,
        <b>Approved with changes</b>, or <b>Revisions required</b> — and sign and date it.{due_txt}
        Your approval releases that file to print.</div>
      <footer><div class="contact">{CONTACT}</div>
        <div class="ftgrid" style="margin-top:5px"><div><span>Page</span><b>1 of {meta.get('pages', 1)}</b></div></div>
      </footer>
    </section>"""


def build_job_html(job, spec, items, approve, base_meta):
    """Whole-job document: cover page + one page per item, with Page X of Y."""
    pages = len(items) + 1
    base_meta = dict(base_meta, pages=pages)
    out = HEAD + _cover_body(job, spec, items, base_meta)
    for idx, it in enumerate(items):
        meta = dict(base_meta, specs=it["specs"], placeholders=it["placeholders"],
                    missing=it["missing"], page=idx + 2, pages=pages)
        out += _item_body(job, it["res"], spec, it["thumb_b64"], approve, meta)
    return out + FOOT


# ---------- CLI ----------
def collect_files(raw):
    """Expand any directory arguments into the artwork files they contain."""
    files = []
    for a in raw:
        if os.path.isdir(a):
            for f in sorted(glob.glob(os.path.join(a, "*"))):
                if os.path.splitext(f)[1].lower() in ART_EXT:
                    files.append(f)
        else:
            files.append(a)
    return files


def main():
    args = sys.argv[1:]
    spec_path = panel_arg = job = approve = ack_review = None
    prepped_by = qc_by = version = fulfillment = None
    book = False
    raw = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--spec":
            spec_path = args[i + 1]; i += 2
        elif a == "--panel":
            panel_arg = args[i + 1]; i += 2
        elif a == "--job":
            job = args[i + 1]; i += 2
        elif a == "--approve":
            approve = args[i + 1]; i += 2
        elif a == "--ack-review":
            ack_review = args[i + 1]; i += 2
        elif a in ("--prepped-by", "--prepped"):
            prepped_by = args[i + 1]; i += 2
        elif a in ("--qc-by", "--qc"):
            qc_by = args[i + 1]; i += 2
        elif a == "--version":
            version = args[i + 1]; i += 2
        elif a == "--fulfillment":
            fulfillment = args[i + 1]; i += 2
        elif a == "--book":
            book = True; i += 1
        else:
            raw.append(a); i += 1
    files = collect_files(raw)
    if not files:
        print('usage: python3 make_proof.py <artwork ...> [--spec ...] [--panel NAME] [--job "Name"]\n'
              '       [--prepped-by "Name"] [--qc-by "Name"] [--version V]\n'
              '       [--fulfillment delivery|pickup] [--approve "Client Name"]\n'
              '       [--ack-review "reason"] [--book]')
        return
    spec = json.load(open(spec_path or proofer.find_default_spec()))
    job = job or spec.get("job", {}).get("name", "Untitled job")
    version = version or spec.get("job", {}).get("version")
    job_no = spec.get("job", {}).get("job_number") or spec.get("job", {}).get("estimate")
    base_meta = {"prepped_by": prepped_by, "qc_by": qc_by, "version": version,
                 "fulfillment": fulfillment, "ack_review": ack_review}

    if len(files) > 1 or book:
        build_job_proof(files, spec, job, job_no, approve, base_meta, panel_arg)
    else:
        build_single_proof(files[0], spec, job, job_no, approve, base_meta, panel_arg)


def build_single_proof(fname, spec, job, job_no, approve, base_meta, panel_arg):
    ext = os.path.splitext(fname)[1].lower()
    try:
        res = proofer.run_checks(fname, spec, panel_arg)
    except Exception as e:
        print("could not read file:", e); return
    if res and res.get("error"):
        print(res["error"]); sys.exit(2)
    if not res:
        print("could not match to a panel — re-run with --panel NAME"); return
    panel = res["panel"]
    specs = panel_specs(panel, spec, base_meta.get("version"))
    placeholders, missing = proof_readiness(specs, base_meta.get("prepped_by"),
                                            base_meta.get("qc_by"), panel.get("finish"))
    placeholders = job_readiness(spec, job, base_meta.get("version")) + placeholders
    if panel.get("needs_confirm"):
        missing = missing + ["panel dimensions UNVERIFIED (AI/OCR-sourced — confirm in the booth file)"]
    ack_review = base_meta.get("ack_review")
    if approve is not None and (is_blank(approve) or looks_placeholder(approve)):
        print(f'⛔ Refusing to stamp APPROVED: approver "{approve}" is blank or a placeholder — '
              f"--approve needs the real client approver's name.")
        sys.exit(1)
    if approve:
        msg = _approval_block(res, placeholders, missing, os.path.basename(fname), ack_review)
        if msg:
            print(msg); sys.exit(1)

    status = "APPROVED" if approve else f"PROOFED ({res['verdict']})"
    if approve and ack_review:
        status = f"APPROVED (REVIEW acknowledged: {ack_review})"
    if approve:
        # log BEFORE stamping: an approval that cannot be logged must not ship
        logged, log_ok = _log_proof_safe(job, job_no, panel["name"], fname, res["verdict"],
                                         status, base_meta.get("version"),
                                         base_meta.get("prepped_by"), base_meta.get("qc_by"),
                                         approve)
        if not log_ok:
            print(f"⛔ Refusing to stamp APPROVED: the approval could not be logged {logged}.\n"
                  f"   Every approval must be recorded in {LOG} — fix the log (install openpyxl, "
                  f"close/unlock the file) and re-run.")
            sys.exit(1)

    thumb = thumbnail(fname, ext)
    meta = dict(base_meta, specs=specs, placeholders=placeholders, missing=missing, page=1, pages=1)
    page = build_proof_html(job, res, spec, b64img(thumb), approve, meta)
    _cleanup(thumb)

    base = re.sub(r"[^A-Za-z0-9]+", "_", os.path.splitext(os.path.basename(fname))[0]).strip("_")
    suffix = "_PROOF_APPROVED" if approve else "_PROOF"
    hp = os.path.abspath(base + suffix + ".html")
    pp = os.path.abspath(base + suffix + ".pdf")
    open(hp, "w").write(page)
    if not approve:
        logged = log_proof(job, job_no, panel["name"], fname, res["verdict"], status,
                           base_meta.get("version"), base_meta.get("prepped_by"),
                           base_meta.get("qc_by"), approve)
    ok = proofer.render_pdf(hp, pp)
    print(f"\nItem {panel['name']}  ·  verdict {res['verdict']}  ·  " +
          (f"APPROVED by {approve}" if approve else "awaiting client sign-off"))
    if not approve and (placeholders or missing):
        print("⚠  NOT client-ready yet — resolve before sending:\n   - "
              + "\n   - ".join(placeholders + [f"{m} not set" for m in missing]))
    print("Proof sheet:", os.path.basename(pp) if ok else os.path.basename(hp) + " (open + print to PDF)")
    print("Logged to  :", logged)


def build_job_proof(files, spec, job, job_no, approve, base_meta, panel_arg):
    if approve:
        print("note: --approve is for a single item; the job document is a draft for per-item sign-off. Ignoring --approve.")
        approve = None
    panel_index = {p["name"]: i for i, p in enumerate(spec.get("panels", []))}
    job_placeholders = job_readiness(spec, job, base_meta.get("version"))
    items, unmatched = [], []
    for n, fname in enumerate(files):
        ext = os.path.splitext(fname)[1].lower()
        try:
            res = proofer.run_checks(fname, spec, None)
        except Exception as e:
            unmatched.append(f"{os.path.basename(fname)} ({e})"); continue
        if res and res.get("error"):
            unmatched.append(f"{os.path.basename(fname)} ({res['error']})"); continue
        if not res:
            unmatched.append(os.path.basename(fname)); continue
        panel = res["panel"]
        specs = panel_specs(panel, spec, base_meta.get("version"))
        placeholders, missing = proof_readiness(specs, base_meta.get("prepped_by"),
                                                base_meta.get("qc_by"), panel.get("finish"))
        placeholders = job_placeholders + placeholders
        if panel.get("needs_confirm"):
            missing = missing + ["panel dimensions UNVERIFIED (AI/OCR-sourced — confirm in the booth file)"]
        thumb = thumbnail(fname, ext, tag=str(n))
        items.append({"panel": panel, "res": res, "specs": specs, "fname": fname,
                      "placeholders": placeholders, "missing": missing,
                      "thumb_b64": b64img(thumb), "_thumb": thumb})
    if not items:
        print("no files matched a panel — name them after the panel (e.g. F1.pdf) or use the single-item mode with --panel"); return
    items.sort(key=lambda it: panel_index.get(it["panel"]["name"], 999))

    html_doc = build_job_html(job, spec, items, approve, base_meta)
    for it in items:
        _cleanup(it.get("_thumb"))

    base = re.sub(r"[^A-Za-z0-9]+", "_", job).strip("_") or "Job"
    hp = os.path.abspath(base + "_JOB_PROOF.html")
    pp = os.path.abspath(base + "_JOB_PROOF.pdf")
    open(hp, "w").write(html_doc)
    for it in items:
        log_proof(job, job_no, it["panel"]["name"], it["fname"], it["res"]["verdict"],
                  "PROOFED (job doc)", base_meta.get("version"),
                  base_meta.get("prepped_by"), base_meta.get("qc_by"), None)
    ok = proofer.render_pdf(hp, pp)
    n_graphics, n_pieces = job_totals(items)
    print(f"\nJOB PROOF · {job}")
    print(f"  {n_graphics} item(s), {n_pieces} piece(s) · {len(items) + 1} pages (cover + {len(items)})")
    for it in items:
        flag = "  ⚠ not client-ready" if (it["placeholders"] or it["missing"]) else ""
        print(f"    - {it['panel']['name']:14} {it['res']['verdict']}{flag}")
    if unmatched:
        print("  unmatched (skipped):", ", ".join(unmatched))
    print("Document:", os.path.basename(pp) if ok else os.path.basename(hp) + " (open + print to PDF)")


def _approval_block(res, placeholders, missing, fname, ack_review=None):
    """Return a refusal message if this item can't be locked-approved, else None.

    Invariant 4: approval must refuse when a check fails or a measurement is
    unconfirmed. Beyond the FAIL refusal: a size check that did not PASS is
    ALWAYS refused (no flag overrides an unverified/wrong finished size); any
    other NEEDS-REVIEW verdict needs an explicit --ack-review \"reason\",
    which is recorded on the proof and in the log row."""
    if res["verdict"] == "FAIL":
        return (f"⛔ Refusing to stamp APPROVED: {fname} FAILS preflight "
                f"({', '.join(k for k, v in res['results'].items() if v[0] == 'FAIL')}). Fix the FAIL(s) first.")
    size_st, size_msg = res["results"].get("size", ("NA", "size was not checked"))
    if size_st != "PASS":
        return (f"⛔ Refusing to stamp APPROVED: the finished size is unverified or wrong — "
                f"size check is {size_st}: {size_msg}\n   A measurement that did not PASS can "
                f"never be approved (--ack-review does not override size); fix the file or "
                f"verify the size first.")
    if placeholders:
        return ("⛔ Refusing to stamp APPROVED: placeholder/blank values would reach the client:\n   - "
                + "\n   - ".join(placeholders) + "\n   Fill them in the booth spec first.")
    if missing:
        return ("⛔ Refusing to stamp APPROVED: not client-ready — " + ", ".join(missing)
                + ".\n   Confirm these in the booth file (and provide --prepped-by / --qc-by) before approving.")
    if res["verdict"] == "REVIEW":
        warns = [k for k, v in res["results"].items() if v[0] == "WARN"]
        if is_blank(ack_review) or looks_placeholder(ack_review):
            return ("⛔ Refusing to stamp APPROVED: preflight verdict is NEEDS REVIEW — WARN on "
                    + ", ".join(warns) + ".\n   Review those items, then re-run with "
                    "--ack-review \"reason\" to approve with a recorded acknowledgment.")
    return None


def _log_proof_safe(*args):
    """(logged, ok) - ok is False when the row could NOT be persisted (openpyxl
    missing, or the workbook load/save raised). Used on the approval path: an
    approval that cannot be logged must not stamp (invariant 4 adjacent - the
    'stamped and logged' promise)."""
    if not openpyxl:
        return "(openpyxl missing - log skipped)", False
    try:
        return log_proof(*args), True
    except Exception as e:
        return f"(log write failed: {e})", False


def _cleanup(path):
    if path:
        try:
            os.remove(path)
        except OSError:
            pass


if __name__ == "__main__":
    main()
