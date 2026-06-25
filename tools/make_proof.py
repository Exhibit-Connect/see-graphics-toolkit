#!/usr/bin/env python3
"""
SEE Proof + Sign-off (Phase 4) - proofing we own, not the vendor's.

From a client's artwork + the booth spec, builds a branded PROOF SHEET that
follows SEE's unified proof standard (per Production's proof-standardization
memo). One artwork = one page, and every page carries:
  - a structured SPEC block (item/tracking #, finish size, material, finishing
    type, qty, sides, seams, revision) pulled from the single-source booth spec;
  - the automated preflight results WITH a status legend;
  - a prominent disclaimer BANNER (not fine print);
  - a 3-option client sign-off (approve as is / approve w/ changes / resubmit);
  - a consistent footer: Prepped by, QC'd by, date, version, delivery/pickup,
    Page X of Y.
Logs every proof to proof_log.xlsx. Approve it to stamp + lock the record; it
refuses to approve a FAIL, or anything still carrying a placeholder/blank value
(no "TBD" or "Name here" reaches a client).

Usage:
    python3 make_proof.py <artwork> [--spec booth_spec.json] [--panel NAME]
        [--job "Name"] [--prepped-by "Name"] [--qc-by "Name"]
        [--version V] [--fulfillment delivery|pickup] [--approve "Client Name"]
"""
import sys, os, re, json, base64, subprocess, datetime, html
import proofer
try:
    import openpyxl
except Exception:
    openpyxl = None

RED = "#ED1C24"
LOG = "proof_log.xlsx"
VCOL = {"PASS": "#2E9E40", "REVIEW": "#F7941E", "FAIL": RED}
VLABEL = {"PASS": "PASS", "REVIEW": "NEEDS REVIEW", "FAIL": "FAIL"}
CONTACT = ("Southeast Exhibits &amp; Events &nbsp;·&nbsp; Orlando | Las Vegas | Atlanta | NJ/NY | Dallas "
           "&nbsp;·&nbsp; SouthEastExhibit.com")
DISCLAIMER = ("This proof is for verifying CONTENT, LAYOUT, COLOR BREAK and SIZE only. On-screen color is "
              "not an exact match to the final printed piece. Check spelling, dimensions and finish "
              "carefully — your approval releases this file to print.")

# literal placeholder / unfilled markers that must never reach a client
PLACEHOLDER_RE = re.compile(r"\b(tbd|tba|todo|name here|placeholder|lorem|xxx+)\b|[<>]|\?\?\?", re.I)


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


def thumbnail(path, ext):
    out = os.path.abspath("_proof_thumb.png")
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
  body { font-family: Arial, Helvetica, sans-serif; color:#1a1a1a; font-size:12px; margin:0; }
  .pill { background:#ED1C24; color:#fff; display:inline-block; padding:5px 14px; border-radius:16px; font-weight:700; font-size:11px; }
  h1 { font-size:19px; margin:9px 0 1px; }
  .meta { color:#555; font-size:11px; margin:1px 0 0; }
  .verdict { display:inline-block; color:#fff; padding:4px 12px; border-radius:7px; font-weight:700; font-size:13px; }
  .legend { font-size:10px; color:#666; margin-left:8px; }
  .legend .dot { display:inline-block; width:9px; height:9px; border-radius:50%; margin:0 3px 0 9px; vertical-align:baseline; }
  .banner { margin:11px 0; padding:9px 13px; background:#FFF4E5; border:1px solid #F7941E; border-left:6px solid #F7941E;
            border-radius:5px; color:#7a4a00; font-size:11px; font-weight:600; line-height:1.35; }
  .caution { margin:11px 0; padding:9px 13px; background:#fde8e8; border:1px solid #ED1C24; border-left:6px solid #ED1C24;
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
  .signbox { margin-top:14px; border:1.5px solid #bbb; border-radius:8px; padding:11px 14px; }
  .sign .st { font-weight:700; color:#ED1C24; margin-bottom:7px; }
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
"""


def build_proof_html(job, res, spec, thumb_b64, approve, meta):
    today = datetime.date.today().strftime("%B %d, %Y")
    verdict = res["verdict"]
    panel = res["panel"]
    specs = meta["specs"]

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

    if approve:
        signoff = (f'<div class="stamp">APPROVED &nbsp;·&nbsp; {html.escape(approve)} &nbsp;·&nbsp; {today}</div>'
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
    if not approve and (meta["placeholders"] or meta["missing"]):
        items = "; ".join(meta["placeholders"] + [f"{m} not set" for m in meta["missing"]])
        caution = (f'<div class="caution">&#9888; DRAFT — not client-ready: {html.escape(items)}. '
                   f'Resolve before sending to the client.</div>')

    version = meta.get("version") or "—"
    prepped = meta.get("prepped_by") or "—"
    qc = meta.get("qc_by") or "—"
    fulfillment = (meta.get("fulfillment") or "—").title() if meta.get("fulfillment") else "—"
    page, pages = meta.get("page", 1), meta.get("pages", 1)
    job_no = spec.get("job", {}).get("job_number") or spec.get("job", {}).get("estimate") or "—"

    head = ('<!doctype html><html><head><meta charset="utf-8"><style>' + CSS_PROOF +
            '</style></head><body>')
    return head + f"""
      <div class="pill">Artwork Proof — for client approval</div>
      <h1>{html.escape(job)} &nbsp;—&nbsp; Item {html.escape(panel['name'])}</h1>
      <div class="meta">Proof version {html.escape(str(version))} &nbsp;·&nbsp; {today} &nbsp;·&nbsp; checked against the booth spec &nbsp;·&nbsp;
        <span class="verdict" style="background:{VCOL[verdict]}">{VLABEL[verdict]}</span>
        <span class="legend">
          <span class="dot" style="background:#2E9E40"></span>Pass
          <span class="dot" style="background:#F7941E"></span>Needs review
          <span class="dot" style="background:#ED1C24"></span>Fail</span>
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
        </div>
      </div>
      <div class="signbox">{signoff}</div>
      <footer>
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
      </footer>
    </body></html>"""


def main():
    args = sys.argv[1:]
    spec_path = panel_arg = job = approve = None
    prepped_by = qc_by = version = fulfillment = None
    files = []
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
        elif a in ("--prepped-by", "--prepped"):
            prepped_by = args[i + 1]; i += 2
        elif a in ("--qc-by", "--qc"):
            qc_by = args[i + 1]; i += 2
        elif a == "--version":
            version = args[i + 1]; i += 2
        elif a == "--fulfillment":
            fulfillment = args[i + 1]; i += 2
        else:
            files.append(a); i += 1
    if not files:
        print('usage: python3 make_proof.py <artwork> [--spec ...] [--panel NAME] [--job "Name"]\n'
              '       [--prepped-by "Name"] [--qc-by "Name"] [--version V]\n'
              '       [--fulfillment delivery|pickup] [--approve "Client Name"]')
        return
    spec = json.load(open(spec_path or proofer.find_default_spec()))
    job = job or spec.get("job", {}).get("name", "Untitled job")
    version = version or spec.get("job", {}).get("version")
    fname = files[0]
    ext = os.path.splitext(fname)[1].lower()

    try:
        res = proofer.run_checks(fname, spec, panel_arg)
    except Exception as e:
        print("could not read file:", e); return
    if not res:
        print("could not match to a panel — re-run with --panel NAME"); return

    panel = res["panel"]
    specs = panel_specs(panel, spec, version)
    placeholders, missing = proof_readiness(specs, prepped_by, qc_by, panel.get("finish"))

    # --- approval gates (refuse to lock anything not client-ready) ---
    if approve:
        if res["verdict"] == "FAIL":
            print(f"⛔ Refusing to stamp APPROVED: {os.path.basename(fname)} FAILS preflight "
                  f"({', '.join(k for k, v in res['results'].items() if v[0] == 'FAIL')}). Fix the FAIL(s) first.")
            return
        if placeholders:
            print("⛔ Refusing to stamp APPROVED: placeholder/blank values would reach the client:\n   - "
                  + "\n   - ".join(placeholders) + "\n   Fill them in the booth spec first.")
            return
        if missing:
            print("⛔ Refusing to stamp APPROVED: required field(s) not set: " + ", ".join(missing)
                  + ".\n   Provide --prepped-by / --qc-by and a confirmed Material before approving.")
            return

    thumb = thumbnail(fname, ext)
    meta = {"specs": specs, "placeholders": placeholders, "missing": missing,
            "prepped_by": prepped_by, "qc_by": qc_by, "version": version,
            "fulfillment": fulfillment, "page": 1, "pages": 1}
    page = build_proof_html(job, res, spec, b64img(thumb), approve, meta)
    if thumb:
        try:
            os.remove(thumb)
        except OSError:
            pass

    base = re.sub(r"[^A-Za-z0-9]+", "_", os.path.splitext(os.path.basename(fname))[0]).strip("_")
    suffix = "_PROOF_APPROVED" if approve else "_PROOF"
    hp = os.path.abspath(base + suffix + ".html")
    pp = os.path.abspath(base + suffix + ".pdf")
    open(hp, "w").write(page)
    status = "APPROVED" if approve else f"PROOFED ({res['verdict']})"
    job_no = spec.get("job", {}).get("job_number") or spec.get("job", {}).get("estimate")
    logged = log_proof(job, job_no, panel["name"], fname, res["verdict"], status,
                       version, prepped_by, qc_by, approve)

    ok = proofer.render_pdf(hp, pp)
    print(f"\nItem {panel['name']}  ·  verdict {res['verdict']}  ·  " +
          (f"APPROVED by {approve}" if approve else "awaiting client sign-off"))
    if not approve and (placeholders or missing):
        notes = placeholders + [f"{m} not set" for m in missing]
        print("⚠  NOT client-ready yet — resolve before sending:\n   - " + "\n   - ".join(notes))
    print("Proof sheet:", os.path.basename(pp) if ok else os.path.basename(hp) + " (open + print to PDF)")
    print("Logged to  :", logged)


if __name__ == "__main__":
    main()
