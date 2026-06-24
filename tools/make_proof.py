#!/usr/bin/env python3
"""
SEE Proof + Sign-off (Phase 4) - proofing we own, not the vendor's.

From a client's artwork + the booth spec, builds a branded one-page PROOF
SHEET: an artwork preview + the automated preflight results (reused from
proofer.py) + a client sign-off block. Logs every proof to proof_log.xlsx.
Approve it to stamp + lock the record. Vendors then receive our proof and
can run their own as a second set of eyes.

Usage:
    python3 make_proof.py <artwork> [--spec booth_spec.json] [--panel NAME]
                          [--job "Name"] [--approve "Client Name"]
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


def log_proof(job, panel, fname, verdict, status, approver):
    if not openpyxl:
        return "(openpyxl missing - log skipped)"
    if os.path.exists(LOG):
        wb = openpyxl.load_workbook(LOG); ws = wb.active
    else:
        wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Proofs"
        ws.append(["Date", "Job", "Panel", "File", "Verdict", "Status", "Approved by"])
    ws.append([datetime.date.today().isoformat(), job, panel, os.path.basename(fname),
               verdict, status, approver or ""])
    wb.save(LOG)
    return LOG


def build_proof_html(job, panel, fname, res, thumb_b64, approve):
    today = datetime.date.today().strftime("%B %d, %Y")
    verdict = res["verdict"]
    rows = ""
    for k in proofer.ORDER:
        if k in res["results"]:
            st, msg = res["results"][k]
            rows += (f'<tr><td class="ck">{k.title()}</td>'
                     f'<td><span class="b" style="background:{proofer.BADGE[st]}">{st}</span></td>'
                     f'<td class="msg">{html.escape(msg)}</td></tr>')
    if approve:
        signoff = (f'<div class="stamp">APPROVED &nbsp;·&nbsp; {html.escape(approve)} &nbsp;·&nbsp; {today}</div>'
                   f'<div class="locknote">Locked on approval. Any change after this requires written approval '
                   f'and triggers an add-on charge.</div>')
    else:
        signoff = ('<div class="sign"><div class="st">Client approval</div>'
                   '<div class="opt">☐ &nbsp;Approved as shown &nbsp;&nbsp;&nbsp; ☐ &nbsp;Approved with the changes noted below</div>'
                   '<div class="lines">Name ________________________ &nbsp; Signature ________________________ &nbsp; Date __________</div>'
                   '<div class="chg">Changes: _______________________________________________________________________</div></div>')
    img = f'<img src="{thumb_b64}">' if thumb_b64 else '<div class="noimg">(preview unavailable)</div>'
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
      @page {{ size: letter portrait; margin: 0.55in; }}
      body {{ font-family: Arial, Helvetica, sans-serif; color:#1a1a1a; font-size:12px; }}
      .pill {{ background:{RED}; color:#fff; display:inline-block; padding:6px 16px; border-radius:16px; font-weight:700; }}
      h1 {{ font-size:20px; margin:10px 0 0; }}
      .meta {{ color:#555; font-size:11.5px; margin:2px 0 10px; }}
      .verdict {{ display:inline-block; color:#fff; background:{VCOL[verdict]}; padding:5px 14px; border-radius:8px; font-weight:700; font-size:14px; }}
      .cols {{ display:flex; gap:16px; margin-top:12px; }}
      .art {{ flex:0 0 42%; border:1px solid #ddd; border-radius:6px; padding:6px; text-align:center; background:#fafafa; }}
      .art img {{ max-width:100%; max-height:340px; }}
      .noimg {{ color:#999; padding:40px 0; }}
      table {{ width:100%; border-collapse:collapse; }}
      th {{ background:#f3f3f3; text-align:left; padding:6px 8px; border-bottom:2px solid #ccc; font-size:10px; text-transform:uppercase; }}
      td {{ padding:6px 8px; border-bottom:1px solid #e8e8e8; vertical-align:top; }}
      td.ck {{ font-weight:700; width:22%; }}
      .b {{ color:#fff; padding:2px 9px; border-radius:10px; font-weight:700; font-size:10px; }}
      .msg {{ font-size:10.5px; }}
      .signbox {{ margin-top:16px; border:1.5px solid #bbb; border-radius:8px; padding:12px 14px; }}
      .sign .st {{ font-weight:700; color:{RED}; margin-bottom:6px; }}
      .sign .opt {{ margin-bottom:14px; }}
      .sign .lines {{ margin-bottom:12px; }}
      .sign .chg {{ color:#555; }}
      .stamp {{ display:inline-block; border:3px solid #2E9E40; color:#2E9E40; font-weight:800; font-size:18px; padding:8px 18px; border-radius:8px; letter-spacing:.04em; }}
      .locknote {{ color:#7a0d12; font-size:11px; margin-top:8px; }}
      footer {{ margin-top:14px; color:#888; font-size:9.5px; border-top:1px solid #ddd; padding-top:6px; }}
    </style></head><body>
      <div class="pill">Artwork Proof — for client approval</div>
      <h1>{html.escape(job)} — panel {html.escape(panel)}</h1>
      <div class="meta">Proof date: {today} &nbsp;·&nbsp; checked against the booth spec &nbsp;·&nbsp; <span class="verdict">{VLABEL[verdict]}</span></div>
      <div class="cols">
        <div class="art">{img}</div>
        <div style="flex:1">
          <table><thead><tr><th>Check</th><th>Result</th><th>Detail</th></tr></thead><tbody>{rows}</tbody></table>
        </div>
      </div>
      <div class="signbox">{signoff}</div>
      <footer>Southeast Exhibits &amp; Events · proof generated &amp; tracked by SEE. WARN/FAIL items resolved before approval; this proof is the record of what was approved.</footer>
    </body></html>"""


def main():
    args = sys.argv[1:]
    spec_path = None
    panel_arg = job = approve = None
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
        else:
            files.append(a); i += 1
    if not files:
        print('usage: python3 make_proof.py <artwork> [--spec ...] [--panel NAME] [--job "Name"] [--approve "Client Name"]')
        return
    spec = json.load(open(spec_path or proofer.find_default_spec()))
    job = job or spec.get("job", {}).get("name", "Untitled job")
    fname = files[0]
    ext = os.path.splitext(fname)[1].lower()

    try:
        res = proofer.run_checks(fname, spec, panel_arg)
    except Exception as e:
        print("could not read file:", e); return
    if not res:
        print("could not match to a panel — re-run with --panel NAME"); return

    if approve and res["verdict"] == "FAIL":
        print(f"⛔ Refusing to stamp APPROVED: {os.path.basename(fname)} FAILS preflight "
              f"({', '.join(k for k, v in res['results'].items() if v[0] == 'FAIL')}). Fix the FAIL(s) first.")
        return

    thumb = thumbnail(fname, ext)
    page = build_proof_html(job, res["panel"]["name"], fname, res, b64img(thumb), approve)
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
    logged = log_proof(job, res["panel"]["name"], fname, res["verdict"], status, approve)

    ok = proofer.render_pdf(hp, pp)
    print(f"\nPanel {res['panel']['name']}  ·  verdict {res['verdict']}  ·  " +
          (f"APPROVED by {approve}" if approve else "awaiting client sign-off"))
    print("Proof sheet:", os.path.basename(pp) if ok else os.path.basename(hp) + " (open + print to PDF)")
    print("Logged to  :", logged)


if __name__ == "__main__":
    main()
