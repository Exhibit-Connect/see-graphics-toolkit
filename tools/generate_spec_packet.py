#!/usr/bin/env python3
"""
SEE Graphic Submission Spec Packet generator.

Reads a booth-spec JSON (the SAME single source of truth the Illustrator
template generator uses) and produces the client-facing spec sheet as
HTML + PDF. Define the booth once; templates and this sheet stay in sync.

Usage:
    python3 generate_spec_packet.py [booth_spec.json]

Free / zero-install: pure-Python HTML, rendered to PDF via headless Chrome.
"""
import json, sys, os, html, base64
import proofer
import branding
import render

RED = "#ED1C24"
def find_default_spec():
    import glob
    here = os.path.dirname(os.path.abspath(__file__))
    for d in (os.getcwd(), os.path.join(here, "..", "examples"),
              os.path.join(os.getcwd(), "examples"), here):
        hits = sorted(glob.glob(os.path.join(d, "*booth_spec*.json")))
        if hits:
            return hits[0]
    return "booth_spec.json"


def esc(v):
    return html.escape(str(v))


def img_data_uri(path):
    """A local image file as a data: URI (so the PDF is self-contained), or ''
    if the path is missing/unreadable."""
    if not path or not os.path.exists(path):
        return ""
    mime = "image/jpeg" if os.path.splitext(path)[1].lower() in (".jpg", ".jpeg") else "image/png"
    try:
        return f"data:{mime};base64," + base64.b64encode(open(path, "rb").read()).decode()
    except OSError:
        return ""


def rendering_data_uri(path):
    """The booth rendering as a data: URI, TRIMMED of surrounding white so the art
    fills the frame (a raw slide export is mostly whitespace and looks small/soft
    embedded). Falls back to the raw image, or '' if there's nothing to embed."""
    if not path or not os.path.exists(path):
        return ""
    try:
        import io
        from PIL import Image, ImageChops
        im = Image.open(path).convert("RGB")
        bbox = ImageChops.difference(im, Image.new("RGB", im.size, (255, 255, 255))).getbbox()
        if bbox:
            pad = 24
            im = im.crop((max(0, bbox[0] - pad), max(0, bbox[1] - pad),
                          min(im.width, bbox[2] + pad), min(im.height, bbox[3] + pad)))
        buf = io.BytesIO()
        im.save(buf, "PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return img_data_uri(path)


def scale_label(s):
    if s == 0.5:
        return "½ scale (build at half size, output at 200%)"
    if s == 1:
        return "full scale (1:1)"
    return f"{s}× scale (output {round(100/s)}%)"


def visible_cell(p):
    parts = []
    if p.get("door"):
        parts.append(f'Door — handle on the {esc(p["door"])}')
    for z in p.get("zones", []):
        if z.get("kind") == "live":
            parts.append(f'<b>Live art area:</b> {z["w"]}″ × {z["h"]}″')
        else:
            parts.append(f'<span class="keep">Keep clear:</span> {esc(z.get("label",""))}')
    return "<br>".join(parts) if parts else '<span class="muted">Full panel</span>'


def build_html(spec):
    job = spec.get("job", {})
    st = spec.get("settings", {})
    ppi = st.get("resolution_ppi", {})
    panels = spec.get("panels", [])
    pending = spec.get("pending_inputs", [])
    excluded = spec.get("excluded", [])
    unverified = proofer.unverified_panels(spec)
    draft = any("TBD" in str(p.get("finish", "")) for p in panels) or bool(pending) or bool(unverified)
    footer_note = ("Sizes marked ⚠ are UNVERIFIED until a person confirms them against the source."
                   if unverified else "For position only; sizes are final unless flagged.")

    rows = ""
    for p in panels:
        finish = p.get("finish", "—")
        fin_cls = ' class="muted"' if "TBD" in str(finish) else ""
        unv = bool(p.get("needs_confirm"))
        unv_badge = ' <span class="unv">⚠ unverified — confirm</span>' if unv else ""
        sided = p.get("sided", "")
        sided_disp = "Double-sided" if sided == "double" else ("Single-sided" if sided == "single" else "—")
        interior = f'<br><span class="muted">Interior: {esc(p["interior_finish"])}</span>' if p.get("interior_finish") else ""
        ftype = p.get("finishing_type") or "—"
        ftype_cls = ' class="muted"' if (ftype == "—" or "TBD" in str(ftype)) else ""
        qty = p.get("quantity", 1)
        note = esc(p.get("note", "")) or '<span class="muted">—</span>'
        rows += f"""<tr>
          <td class="pname">{esc(p['name'])}</td>
          <td class="size{' unvsize' if unv else ''}">{p['w']}″ × {p['h']}″{unv_badge}</td>
          <td{fin_cls}>{esc(finish)}{interior}</td>
          <td{ftype_cls}>{esc(ftype)}</td>
          <td class="qty">{esc(qty)}</td>
          <td>{sided_disp}</td>
          <td class="vis">{visible_cell(p)}</td>
          <td class="note">{note}</td>
        </tr>"""

    excl = ""
    if excluded:
        items = "".join(f"<li><b>{esc(e['name'])}</b> — {esc(e.get('reason',''))}</li>" for e in excluded)
        excl = f'<h2>Not in this packet</h2><ul class="plain">{items}</ul>'

    banner = ""
    if unverified:
        names = ", ".join(esc(n) for n in unverified)
        banner += (f'<div class="unvbanner">⚠ UNVERIFIED DIMENSIONS — {len(unverified)} panel(s) were read by AI/OCR and '
                   f'are <u>not yet confirmed by a person</u>. Do not treat these sizes as final or send this sheet to the '
                   f'client until they are checked against the source: <b>{names}</b>.</div>')
    if pending:
        pend = "".join(f"<li>{esc(x)}</li>" for x in pending)
        sizes_claim = "sizes are final, the flagged details are not" if not unverified else "the flagged items below are not final"
        banner += f'<div class="draft">DRAFT — items below are still being confirmed; {sizes_claim}:<ul>{pend}</ul></div>'

    bleed = st.get("bleed_per_side_in", 1.0)
    specs = f"""
      <li><b>Scale:</b> {esc(scale_label(st.get('scale', 0.5)))}</li>
      <li><b>Bleed:</b> add {bleed}″ on each side ({bleed*2}″ total to the overall width and height)</li>
      <li><b>Color:</b> {esc(st.get('color_mode','CMYK / Pantone'))}</li>
      <li><b>Resolution:</b> {ppi.get('min',120)}–{ppi.get('max',150)} ppi at scale (no more than {ppi.get('max',150)})</li>
      <li><b>Fonts:</b> {esc(st.get('fonts','convert to outlines'))}</li>
      <li><b>Printer marks:</b> {esc(st.get('printer_marks','disabled'))}</li>
      <li><b>Safe margin:</b> keep logos &amp; text ~{esc(st.get('safe_margin_in',4))}″ in from the edges</li>
      <li><b>Submit via:</b> {esc(', '.join(st.get('submission', [])))}</li>
    """

    meta = " &nbsp;|&nbsp; ".join(
        f"<b>{esc(k.title())}:</b> {esc(v)}" for k, v in [
            ("Job #", job.get("job_number", "") or job.get("estimate", "")),
            ("Show", job.get("show", "")), ("Booth", job.get("booth_size", "")),
            ("Version", job.get("version", "")), ("Location", job.get("location", "")),
            ("Due date", job.get("due_date", "")),
        ] if v)

    render_block = ""
    if spec.get("__rendering_uri"):
        render_block = (f'<section class="placement"><h2>Graphic placement</h2>'
                        f'<div class="render"><img src="{spec["__rendering_uri"]}" '
                        f'alt="Booth rendering with each graphic labeled">'
                        f'<div class="rcap">Booth rendering — each graphic is labeled; see the sizes on the next page.</div></div></section>')

    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
      @page {{ size: letter landscape; margin: 0.5in; }}
      * {{ box-sizing: border-box; }}
      body {{ font-family: Arial, Helvetica, sans-serif; color: #1a1a1a; margin: 0; }}
      .pill {{ background:{RED}; color:#fff; display:inline-block; padding:6px 18px; border-radius:18px; font-weight:700; font-size:15px; }}
      h1 {{ font-size: 26px; margin: 10px 0 2px; }}
      .meta {{ color:#444; font-size:12px; margin-bottom:14px; }}
      h2 {{ color:{RED}; font-size:15px; border-bottom:2px solid {RED}; padding-bottom:3px; margin:18px 0 8px; }}
      table {{ width:100%; border-collapse:collapse; font-size:11.5px; }}
      th {{ background:#f3f3f3; text-align:left; padding:6px 8px; border-bottom:2px solid #ccc; font-size:11px; text-transform:uppercase; letter-spacing:.02em; }}
      td {{ padding:6px 8px; border-bottom:1px solid #e6e6e6; vertical-align:top; }}
      .pname {{ font-weight:700; white-space:nowrap; }}
      .size {{ font-variant-numeric: tabular-nums; white-space:nowrap; font-weight:600; }}
      .qty {{ text-align:center; font-weight:600; }}
      .vis {{ font-size:10.8px; }}
      .note {{ color:#555; font-size:10.8px; }}
      .muted {{ color:#9a9a9a; }}
      .keep {{ color:{RED}; font-weight:700; }}
      ul.specs {{ columns:2; font-size:12px; line-height:1.5; }}
      ul.plain {{ font-size:12px; }}
      .draft {{ background:#fff4f4; border:1px solid {RED}; color:#7a0d12; padding:8px 12px; border-radius:8px; font-size:11.5px; margin:10px 0; }}
      .draft ul {{ margin:4px 0 0; }}
      .unvbanner {{ background:{RED}; color:#fff; padding:10px 14px; border-radius:8px; font-size:12px; font-weight:600; margin:10px 0; line-height:1.4; }}
      .unv {{ color:{RED}; font-weight:700; font-size:9.5px; white-space:nowrap; }}
      .unvsize {{ color:{RED}; }}
      footer {{ margin-top:18px; color:#888; font-size:10px; border-top:1px solid #ddd; padding-top:6px; }}
      .placement {{ page-break-after: always; }}
      .render {{ margin:30px auto 8px; text-align:center; }}
      .render img {{ display:block; margin:0 auto; max-width:82%; max-height:430px; border:1px solid #e2e2e2;
                     border-radius:8px; padding:12px; background:#fff; box-shadow:0 1px 5px rgba(0,0,0,.09); }}
      .rcap {{ color:#888; font-size:10px; margin-top:6px; text-align:center; }}
      {branding.BRAND_CSS}
    </style></head><body>
      {branding.header_html("Graphic Submission Spec Packet")}
      <h1>{esc(job.get('name','') or job.get('client',''))}</h1>
      <div class="meta">{meta}</div>
      {banner}
      {render_block}
      <h2>Graphics to submit</h2>
      <table>
        <thead><tr><th>Panel</th><th>Finished size (W × H)</th><th>Material</th><th>Finishing type</th><th>Qty</th><th>Sided</th><th>Visible area / keep-clear</th><th>Notes</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
      <h2>How to build your files</h2>
      <ul class="specs">{specs}</ul>
      {excl}
      <footer>Generated from {esc(os.path.basename(spec.get('__source','booth spec')))} · Southeast Exhibits &amp; Events. {footer_note}</footer>
    </body></html>"""


def main():
    spec_path = sys.argv[1] if len(sys.argv) > 1 else find_default_spec()
    spec = json.load(open(spec_path))
    spec["__source"] = os.path.basename(spec_path)
    rp = spec.get("rendering")
    if rp and not os.path.isabs(rp):
        rp = os.path.join(os.path.dirname(os.path.abspath(spec_path)), rp)
    spec["__rendering_uri"] = rendering_data_uri(rp)
    base = os.path.splitext(os.path.basename(spec_path))[0].replace("booth_spec_", "")
    html_path = os.path.abspath(f"{base}_Spec_Packet.html")
    pdf_path = os.path.abspath(f"{base}_Spec_Packet.pdf")
    unv = proofer.unverified_panels(spec)
    open(html_path, "w").write(build_html(spec))
    print("HTML:", html_path)
    if unv:
        print(f"⚠  {len(unv)} UNVERIFIED panel(s) (AI/OCR-sourced): {', '.join(unv)} — confirm before sending to the client.")

    if render.html_to_pdf(html_path, pdf_path):
        print("PDF: ", pdf_path, f"({os.path.getsize(pdf_path)} bytes)")
    else:
        print("PDF step skipped — open the HTML and Print -> Save as PDF.")


if __name__ == "__main__":
    main()
