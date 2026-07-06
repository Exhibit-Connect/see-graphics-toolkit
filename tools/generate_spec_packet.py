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

RED = branding.RED


def cover_bg_svg(w=1600, h=900):
    """SEE's signature cover background — big soft angular chevrons in neutral grays,
    recreated (not copied) to match the official 2025 client-deck cover. Pure/testable
    so the cover never depends on a copyrighted raster."""
    base, light, mid, dark = "#ededed", "#f5f5f5", "#e9e9e9", "#e0e0e0"

    def chevron(cx, cy, arm, thick, tone):
        pts = [(-arm, -arm - thick), (-arm + thick, -arm - thick), (thick, 0),
               (-arm + thick, arm + thick), (-arm, arm + thick), (0, 0)]
        return f'<polygon points="{" ".join(f"{cx+x:.0f},{cy+y:.0f}" for x, y in pts)}" fill="{tone}"/>'

    conf = [(260, 120, light), (520, 300, mid), (760, -40, dark), (1020, 360, light),
            (1280, 120, mid), (200, 640, mid), (700, 760, dark), (1180, 700, light),
            (1480, 520, mid), (60, 300, dark)]
    body = "".join(chevron(cx, cy, 300, 150, t) for cx, cy, t in conf)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">'
            f'<rect width="{w}" height="{h}" fill="{base}"/>'
            f'<g transform="rotate(-32 {w/2} {h/2})" opacity="0.8">{body}</g></svg>')


def cover_bg_data_uri():
    return "data:image/svg+xml;base64," + base64.b64encode(cover_bg_svg().encode()).decode()


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

    # ---- Assemble the client packet as a branded 16in x 9in slide deck that mirrors
    # SEE's official 2025 client-presentation deck: Cover (client + show), Who We Are,
    # project Info, the labeled graphic-placement rendering, Graphics to Submit, How to
    # Build, the official Artwork Guidelines, and a Thank You close. The static official
    # pages (Who We Are / Guidelines / Thank You) embed only when the local-only
    # assets/brand/ folder is present; on a public checkout they cleanly drop out.
    logo = branding.logo_data_uri()
    logo_tag = (f'<img class="slide-logo" src="{logo}" alt="Southeast Exhibits &amp; Events">'
                if logo else '<div class="slide-wordmark">SOUTHEAST EXHIBITS &amp; EVENTS</div>')

    client_only = esc(job.get("client", "") or job.get("name", ""))
    show = esc(job.get("show", ""))
    booth = esc(job.get("booth_size", ""))

    cover_sub = " &nbsp;·&nbsp; ".join(x for x in [show, (booth + " booth" if booth else "")] if x)
    cover_base = branding.brand_page_data_uri("cover_base")
    if cover_base:
        # 1:1 with SEE's official cover: their exact page (geometric background + the red
        # title bar, text filtered out) is the backdrop; we just drop the wordmark and the
        # client name into place, positioned to match the template.
        cover_slide = f"""
      <section class="slide slide-coverreal" style="background:#ededed url('{cover_base}') center/cover no-repeat;">
        <div class="cov-wordmark">SOUTHEAST EXHIBITS</div>
        <div class="cov-client">{client_only or 'CLIENT NAME'}</div>
      </section>"""
    else:
        # Fallback (no brand assets, e.g. a public checkout): recreated geometric background.
        cover_slide = f"""
      <section class="slide slide-cover" style="background:#ededed url('{cover_bg_data_uri()}') center/cover no-repeat;">
        <div class="cover-block">
          <div class="cover-eyebrow">Graphic Submission Spec Packet</div>
          <div class="cover-co">SOUTHEAST<br>EXHIBITS</div>
          <div class="cover-client">{client_only or 'CLIENT'}</div>
          <div class="cover-sub">{cover_sub}</div>
        </div>
      </section>"""

    info_pairs = [("Version", esc(job.get("version", ""))),
                  ("Show Date", esc(job.get("show_date", ""))),
                  ("Designer", esc(job.get("designer", ""))),
                  ("Account Rep", esc(job.get("rep", ""))),
                  ("Job #", esc(job.get("job_number", "") or job.get("estimate", ""))),
                  ("Graphic Due", esc(job.get("due_date", ""))),
                  ("Location", esc(job.get("location", "")))]
    info_rows = "".join(f'<div class="info-row"><span class="il">{k}</span><span class="iv">{v}</span></div>'
                        for k, v in info_pairs if v)
    info_slide = f"""
      <section class="slide slide-info">
        {logo_tag}
        <div class="info-block">
          <div class="info-show">{show or client_only}</div>
          <div class="info-booth">{booth or 'BOOTH'}</div>
          <div class="info-list">{info_rows}</div>
        </div>
      </section>"""

    render3d_slide = ""
    if spec.get("__rendering_3d_uri"):
        render3d_slide = f"""
      <section class="slide slide-place">
        {logo_tag}
        <div class="pill-head">Booth Rendering</div>
        <div class="place-wrap">
          <img class="place-img" src="{spec['__rendering_3d_uri']}" alt="3D rendering of the finished booth">
          <div class="place-cap">3D design rendering of the finished booth.</div>
        </div>
      </section>"""

    render_slide = ""
    if spec.get("__rendering_uri"):
        render_slide = f"""
      <section class="slide slide-place">
        {logo_tag}
        <div class="pill-head">Graphic Placement</div>
        <div class="place-wrap">
          <img class="place-img" src="{spec['__rendering_uri']}" alt="Booth rendering with each graphic labeled">
          <div class="place-cap">Each graphic is labeled — the exact finished sizes are on the next page.</div>
        </div>
      </section>"""

    graphics_slide = f"""
      <section class="slide slide-doc">
        {logo_tag}
        <div class="pill-head">Graphics to Submit</div>
        <div class="doc-body">
          {banner}
          <table>
            <thead><tr><th>Panel</th><th>Finished size (W × H)</th><th>Material</th><th>Finishing type</th><th>Qty</th><th>Sided</th><th>Visible area / keep-clear</th><th>Notes</th></tr></thead>
            <tbody>{rows}</tbody>
          </table>
          {excl}
          <div class="disclaimer">Generated from {esc(os.path.basename(spec.get('__source','booth spec')))} · Southeast Exhibits &amp; Events. {footer_note}</div>
        </div>
      </section>"""

    # Artwork Guidelines rebuilt as a NATIVE 16×9 slide (was a pasted image of the
    # official one-pager) — same content/look (red section heads, the accepted-format
    # app chips, the copyright line), laid out cleanly and filled from this booth file.
    def afmt(txt, bg, fg):
        return f'<span class="afmt" style="background:{bg};color:{fg}">{txt}</span>'
    formats = (afmt("Ps", "#001E36", "#31A8FF") + afmt("Ai", "#330000", "#FF9A00")
               + afmt("Id", "#49021F", "#FF3366") + afmt("PDF", "#F40F02", "#fff"))
    submit = esc(", ".join(st.get("submission", [])) or "WeTransfer, Dropbox or Adobe Creative Cloud")
    guide_bg = branding.brand_page_data_uri("guidelines_bg")
    guide_style = f" style=\"background:#fff url('{guide_bg}') center/cover no-repeat;\"" if guide_bg else ""
    guidelines_slide = f"""
      <section class="slide slide-guidelines"{guide_style}>
        {logo_tag}
        <div class="pill-head">Artwork Guidelines</div>
        <div class="ag-cols">
          <div class="ag-col">
            <div class="ag-h">Artwork Sizing &amp; Bleeds</div>
            <ul><li>Build files at either <b>½ scale</b> or full scale</li>
                <li>Add <b>{bleed*2:g}″ bleed</b> to the overall width &amp; height ({bleed:g}″ per side)</li>
                <li>Keep logos &amp; text about <b>{esc(st.get('safe_margin_in',4))}″</b> in from the edges (safe area)</li></ul>
            <div class="ag-h">Color Formats</div>
            <ul><li>CMYK</li><li>Pantone colors</li></ul>
            <div class="ag-h">Text / Fonts</div>
            <ul><li>Convert all fonts to <b>outlines</b></li></ul>
          </div>
          <div class="ag-col">
            <div class="ag-h">Accepted File Formats</div>
            <div class="ag-formats">{formats}</div>
            <div class="ag-h">Resolution &amp; Output</div>
            <ul><li>{ppi.get('min',120)}–{ppi.get('max',150)} ppi at scale (no more than {ppi.get('max',150)})</li>
                <li>Printer marks: {esc(st.get('printer_marks','disabled'))}</li></ul>
            <div class="ag-h">Artwork Submission</div>
            <ul><li>Submit final artwork via {submit}</li></ul>
          </div>
        </div>
        <div class="ag-foot">© Copyright Protected. This is the property of Southeast Exhibits and must not be reproduced in part or full without its permission.</div>
      </section>"""

    who = branding.brand_page_data_uri("who_we_are")
    thanks = branding.brand_page_data_uri("thank_you")
    who_slide = (f'<section class="slide slide-full"><img class="fullbleed" src="{who}" '
                 f'alt="Who we are — Southeast Exhibits &amp; Events"></section>') if who else ""
    thanks_slide = (f'<section class="slide slide-full"><img class="fullbleed" src="{thanks}" '
                    f'alt="Thank you — Southeast Exhibits &amp; Events"></section>') if thanks else ""

    slides = "".join([cover_slide, who_slide, info_slide, render3d_slide, render_slide,
                      graphics_slide, guidelines_slide, thanks_slide])

    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
      @page {{ size: 16in 9in; margin: 0; }}
      * {{ box-sizing: border-box; }}
      html, body {{ margin:0; padding:0; }}
      body {{ font-family: {branding.FONT_STACK}; color:#1a1a1a; -webkit-print-color-adjust:exact; print-color-adjust:exact; }}
      .slide {{ position:relative; width:16in; height:9in; overflow:hidden; background:#fff; }}
      .slide + .slide {{ page-break-before: always; }}
      .slide-logo {{ position:absolute; top:0.6in; left:0.7in; height:0.58in; width:auto; z-index:3; }}
      .slide-wordmark {{ position:absolute; top:0.66in; left:0.7in; font-weight:800; font-size:22px; color:#111; z-index:3; }}
      .pill-head {{ position:absolute; top:0.62in; right:0.7in; background:{RED}; color:#fff; font-size:24px;
                    font-weight:800; padding:10px 26px; border-radius:10px; letter-spacing:.01em; }}

      /* 1:1 cover — text overlaid on SEE's real cover page (bbox-matched to the template) */
      .slide-coverreal {{ position:relative; }}
      .cov-wordmark {{ position:absolute; left:6.7%; top:13.6%; font-size:114px; font-weight:800;
                       letter-spacing:-3px; color:#141414; white-space:nowrap; line-height:1; }}
      .cov-client {{ position:absolute; left:7.0%; top:29.0%; font-size:62px; font-weight:800;
                     color:#fff; white-space:nowrap; line-height:1; }}

      .slide-cover {{ background-color:#ededed; }}
      .cover-block {{ position:absolute; left:0.95in; top:2.55in; }}
      .cover-eyebrow {{ font-size:20px; font-weight:700; letter-spacing:.22em; text-transform:uppercase; color:{RED}; margin-bottom:16px; }}
      .cover-co {{ font-size:92px; font-weight:800; line-height:0.96; letter-spacing:-2px; color:#141414; }}
      .cover-client {{ display:inline-block; margin-top:20px; background:{RED}; color:#fff; font-size:52px; font-weight:800; padding:6px 28px; letter-spacing:.5px; }}
      .cover-sub {{ margin-top:28px; font-size:26px; color:#3a3a3a; font-weight:500; }}

      .info-block {{ position:absolute; left:0.95in; top:1.95in; right:0.9in; }}
      .info-show {{ font-size:72px; font-weight:800; line-height:1.0; letter-spacing:-1.5px; color:#141414; }}
      .info-booth {{ display:inline-block; margin-top:14px; background:{RED}; color:#fff; font-size:44px; font-weight:800; padding:6px 24px; }}
      .info-list {{ margin-top:42px; font-size:26px; color:#222; max-width:10in; }}
      .info-row {{ display:flex; padding:8px 0; border-bottom:1px solid #ececec; }}
      .info-row .il {{ width:3.3in; color:#777; font-weight:700; }}
      .info-row .iv {{ font-weight:600; }}

      .slide-place {{ background:#fafafa; }}
      .place-wrap {{ position:absolute; top:1.75in; left:0.7in; right:0.7in; bottom:0.6in;
                     display:flex; flex-direction:column; align-items:center; justify-content:center; }}
      .place-img {{ max-width:100%; max-height:5.9in; border:1px solid #e2e2e2; border-radius:10px; background:#fff; box-shadow:0 2px 12px rgba(0,0,0,.10); }}
      .place-cap {{ margin-top:16px; color:#777; font-size:17px; }}

      .doc-body {{ position:absolute; top:1.75in; left:0.7in; right:0.7in; }}
      table {{ width:100%; border-collapse:collapse; font-size:15px; }}
      th {{ background:#f3f3f3; text-align:left; padding:9px 11px; border-bottom:2px solid #ccc; font-size:13px; text-transform:uppercase; letter-spacing:.02em; }}
      td {{ padding:9px 11px; border-bottom:1px solid #e6e6e6; vertical-align:top; }}
      .pname {{ font-weight:700; white-space:nowrap; }}
      .size {{ font-variant-numeric: tabular-nums; white-space:nowrap; font-weight:600; }}
      .qty {{ text-align:center; font-weight:600; }}
      .vis {{ font-size:13.5px; }}
      .note {{ color:#555; font-size:13.5px; }}
      .muted {{ color:#9a9a9a; }}
      .keep {{ color:{RED}; font-weight:700; }}
      h2 {{ color:{RED}; font-size:19px; border-bottom:2px solid {RED}; padding-bottom:4px; margin:24px 0 10px; }}
      ul.specs {{ columns:2; column-gap:0.8in; font-size:23px; line-height:1.95; padding-left:26px; margin:0; }}
      ul.specs li {{ margin-bottom:6px; break-inside:avoid; }}
      ul.plain {{ font-size:16px; line-height:1.55; }}
      .draft {{ background:#fff4f4; border:1px solid {RED}; color:#7a0d12; padding:11px 15px; border-radius:8px; font-size:15px; margin:0 0 12px; }}
      .draft ul {{ margin:4px 0 0; }}
      .unvbanner {{ background:{RED}; color:#fff; padding:12px 16px; border-radius:8px; font-size:15px; font-weight:600; margin:0 0 12px; line-height:1.4; }}
      .unv {{ color:{RED}; font-weight:700; font-size:12px; white-space:nowrap; }}
      .unvsize {{ color:{RED}; }}
      .disclaimer {{ margin-top:18px; color:#999; font-size:13px; border-top:1px solid #e2e2e2; padding-top:9px; }}

      .slide-full {{ padding:0; }}
      .fullbleed {{ width:16in; height:9in; object-fit:cover; display:block; }}

      .ag-cols {{ position:absolute; top:1.9in; left:0.75in; right:0.75in; display:flex; gap:1in; }}
      .ag-col {{ flex:1; }}
      .ag-h {{ color:{RED}; font-size:26px; font-weight:800; border-bottom:2px solid {RED}; padding-bottom:5px; margin:0 0 10px; }}
      .ag-col ul {{ margin:0 0 30px; padding-left:24px; font-size:21px; line-height:1.5; color:#222; }}
      .ag-col li {{ margin-bottom:6px; }}
      .ag-formats {{ margin:2px 0 30px; }}
      .afmt {{ display:inline-block; width:0.7in; height:0.7in; line-height:0.7in; text-align:center;
               border-radius:12px; font-weight:800; font-size:22px; margin-right:14px; vertical-align:middle; }}
      .ag-foot {{ position:absolute; left:0.75in; right:0.75in; bottom:0.5in; text-align:center;
                  color:#888; font-size:13px; border-top:1px solid #e2e2e2; padding-top:10px; }}
    </style></head><body>
      {slides}
    </body></html>"""


def main():
    spec_path = sys.argv[1] if len(sys.argv) > 1 else find_default_spec()
    spec = json.load(open(spec_path))
    spec["__source"] = os.path.basename(spec_path)
    def _resolve(field):
        p = spec.get(field)
        if p and not os.path.isabs(p):
            p = os.path.join(os.path.dirname(os.path.abspath(spec_path)), p)
        return rendering_data_uri(p)
    spec["__rendering_uri"] = _resolve("rendering")            # labeled graphic-placement key
    spec["__rendering_3d_uri"] = _resolve("rendering_3d")      # photoreal 3D booth render
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
