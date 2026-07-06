#!/usr/bin/env python3
"""
SEE Client-Ready Design Templates.

Turns the booth file into a client-facing DESIGN TEMPLATE they can open without
Illustrator: ONE multi-page PDF (a cover + one page per panel) where each page
shows that panel's artboard with the bleed / trim / safe / keep-clear / live /
door guides, the exact dimensions, and how to build the file. Clients design
straight onto the real guides -> far fewer wrong-size / no-bleed submissions.

Same single source of truth as everything else, and the guide geometry is the
SAME function the preview uses (preview_templates.panel_guides_svg), so the
client template can never disagree with the production template.

Usage:
    python3 tools/client_templates.py [booth_spec.json] [--per-panel]

Default: one <Job>_Client_Templates.pdf. --per-panel ALSO writes one PDF each.
Free / zero-install: pure-Python HTML/SVG, PDF via headless Chrome.
"""
import json, sys, os, re, html
import branding
import render
import preview_templates as pt

MAX_BUILD_IN = 226.0  # Illustrator's ~227" artboard limit, measured at build scale


def find_default_spec():
    return pt.find_default_spec()


def re_safe(s):
    return re.sub(r"[^A-Za-z0-9]+", "_", str(s)).strip("_") or "panel"


# ---------- pure helpers ----------
def oversized_panels(spec):
    """Panels too big for a single Illustrator artboard at build scale — the
    .jsx skips these to tile/seam separately, and so do we (the page shows a
    notice instead of an artboard). Returns the list of oversized panel dicts.
    Pure (mirrors the .jsx MAX_AB_PT check)."""
    st = spec.get("settings", {})
    bleed = st.get("bleed_per_side_in", 1.0)
    scale = st.get("scale", 0.5)
    out = []
    for p in spec.get("panels", []):
        bw = (p.get("w", 0) + 2 * bleed) * scale
        bh = (p.get("h", 0) + 2 * bleed) * scale
        if bw > MAX_BUILD_IN or bh > MAX_BUILD_IN:
            out.append(p)
    return out


def fit_px(panel, settings, max_w=860, max_h=470):
    """Pixels-per-inch so the panel's bleed box fits the page draw area. Pure."""
    bleed = settings.get("bleed_per_side_in", 1.0)
    bw = panel.get("w", 1) + 2 * bleed
    bh = panel.get("h", 1) + 2 * bleed
    return max(0.5, min(max_w / bw, max_h / bh))


def caption_rows(panel, settings):
    """The client-facing build numbers for one panel (trim, file-with-bleed,
    bleed, safe, material, finishing, sides, qty). Pure."""
    bleed = settings.get("bleed_per_side_in", 1.0)
    safe = settings.get("safe_margin_in", 4.0)
    w, h = panel.get("w"), panel.get("h")
    sided = str(panel.get("sided", "")).strip().lower()
    sided_lbl = {"single": "Single-sided", "double": "Double-sided"}.get(sided, panel.get("sided") or "—")
    return [
        ("Finished (trim) size", f'{w:g}" W × {h:g}" H' if (w and h) else "—"),
        ("File size WITH bleed", f'{w + 2*bleed:g}" W × {h + 2*bleed:g}" H' if (w and h) else "—"),
        ("Bleed", f'{bleed:g}" on every side'),
        ("Safe margin", f'keep text & logos {safe:g}" in from the trim'),
        ("Material", panel.get("finish") or "—"),
        ("Finishing type", panel.get("finishing_type") or "—"),
        ("Sides", sided_lbl),
        ("Quantity", str(panel.get("quantity", 1))),
    ]


# ---------- HTML ----------
def _colorkey():
    items = [("Bleed — extend art to here", pt.C["bleed"]),
             ("Trim — the finished cut", pt.C["trim"]),
             ("Safe — keep text inside", pt.C["safe"]),
             ("Keep-clear — no artwork", pt.C["keep"]),
             ("Live art area", pt.C["live"]),
             ("Door + handle/lock holes", pt.C["door"])]
    lis = "".join(f'<div class="ck"><span class="sw" style="border-color:{c}"></span>{html.escape(t)}</div>'
                  for t, c in items)
    return f'<div class="key"><div class="keyhd">Guide colors</div>{lis}</div>'


def _howto():
    return ("<b>How to use this template:</b> Build your artwork to the <b>file size with bleed</b> shown. "
            "Extend backgrounds and photos all the way out to the <b>cyan bleed</b> line. Keep logos and text "
            "inside the <b>magenta safe</b> line. Put nothing important in <b>orange keep-clear</b> zones. "
            "Export a CMYK PDF with fonts outlined and printer marks off. Please don't move or resize the guides.")


def panel_page_html(panel, spec, page, pages, oversized=False):
    st = spec.get("settings", {})
    door = spec.get("door_standard", {})
    name = panel.get("name", "?")
    cap = "".join(f'<tr><td class="cl">{html.escape(l)}</td><td class="cv">{html.escape(str(v))}</td></tr>'
                  for l, v in caption_rows(panel, st))
    if oversized:
        art = (f'<div class="oversize">&#9888; This piece is too large for one template '
               f'({panel.get("w")}" × {panel.get("h")}"). It is printed in sections and seamed together — '
               f'our team will handle the tiling. Build to the finished size + bleed listed, full resolution.</div>')
    else:
        px = fit_px(panel, st)
        bleed = st.get("bleed_per_side_in", 1.0)
        pbw = (panel.get("w", 1) + 2 * bleed) * px
        pbh = (panel.get("h", 1) + 2 * bleed) * px
        frag = pt.panel_guides_svg(panel, st, door, 5, 5, px)
        art = (f'<svg class="tpl" width="{pbw + 10:.0f}" height="{pbh + 10:.0f}" '
               f'viewBox="0 0 {pbw + 10:.0f} {pbh + 10:.0f}" xmlns="http://www.w3.org/2000/svg" '
               f'font-family="Helvetica Neue, Helvetica, Arial, sans-serif">'
               f'<rect x="0" y="0" width="{pbw + 10:.0f}" height="{pbh + 10:.0f}" fill="#fff"/>{frag}</svg>'
               f'<div class="shown">Shown reduced to fit the page — build at the TRUE sizes listed at right.</div>')
    note = panel.get("note")
    note_html = f'<div class="note"><b>Note:</b> {html.escape(str(note))}</div>' if note else ""
    return f"""<section class="page">
      <div class="phead"><div class="pill">Design Template — {html.escape(str(name))}</div>
        <div class="pgnum">Page {page} of {pages}</div></div>
      <div class="cols">
        <div class="art">{art}</div>
        <div class="side">
          <table class="cap">{cap}</table>
          {note_html}
          {_colorkey()}
        </div>
      </div>
      <div class="howto">{_howto()}</div>
      <footer><div class="ft">{branding.CONTACT}</div><div class="pg">Page {page} of {pages}</div></footer>
    </section>"""


def _cover_page(spec, panels, over_names, pages):
    j = spec.get("job", {}) or {}
    fields = [("Client", j.get("client")), ("Show", j.get("show")), ("Booth", j.get("booth_size")),
              ("Job #", j.get("job_number") or j.get("estimate")), ("Version", j.get("version")),
              ("Due date", j.get("due_date"))]
    grid = "".join(f'<div><span>{html.escape(l)}</span><b>{html.escape(str(v or "—"))}</b></div>'
                   for l, v in fields)
    lis = ""
    for i, p in enumerate(panels, 1):
        w, h = p.get("w"), p.get("h")
        size = f'{w:g}" × {h:g}"' if (w and h) else "—"
        tag = ' <span class="ov">tile/seam</span>' if p.get("name") in over_names else ""
        lis += (f'<tr><td>{i}</td><td><b>{html.escape(str(p.get("name", "?")))}</b>{tag}</td>'
                f'<td>{html.escape(size)}</td><td>{html.escape(p.get("finish") or "—")}</td></tr>')
    return f"""<section class="page">
      {branding.header_html("Client Design Templates")}
      <h1>{html.escape(j.get('name', '') or j.get('client', '') or 'Booth')}</h1>
      <div class="jobgrid">{grid}</div>
      <div class="intro">One page per graphic follows. Each shows the exact artboard with bleed, trim and
        safe guides — design directly on it, then send us a print-ready PDF per the build rules below.</div>
      <table class="summary"><thead><tr><th>#</th><th>Graphic</th><th>Finished size (W × H)</th><th>Material</th></tr></thead>
        <tbody>{lis}</tbody></table>
      <div class="howto">{_howto()} <i>(Each page shows the guide-color key.)</i></div>
      <footer><div class="ft">{branding.CONTACT}</div><div class="pg">Page 1 of {pages}</div></footer>
    </section>"""


CSS = f"""
  @page {{ size: letter landscape; margin: 0.5in; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; color:#1a1a1a; margin:0; font-size:12px; }}
  .page {{ page-break-after: always; }}
  .page:last-child {{ page-break-after: auto; }}
  .phead {{ display:flex; justify-content:space-between; align-items:center; }}
  .pill {{ background:{branding.RED}; color:#fff; padding:5px 14px; border-radius:16px; font-weight:700; font-size:13px; }}
  .pgnum {{ color:#999; font-size:10px; }}
  h1 {{ font-size:23px; margin:12px 0 4px; }}
  .cols {{ display:flex; gap:18px; margin-top:8px; align-items:flex-start; }}
  .art {{ flex:0 0 auto; max-width:62%; border:1px solid #e2e2e2; border-radius:6px; padding:8px; background:#fafafa; text-align:center; }}
  svg.tpl {{ max-width:100%; height:auto; }}
  .shown {{ color:#999; font-size:9.5px; margin-top:5px; }}
  .oversize {{ color:#7a0d12; background:#fde8e8; border:1px solid {branding.RED}; border-radius:6px; padding:18px 16px; font-weight:600; max-width:430px; line-height:1.45; }}
  .side {{ flex:1; }}
  table.cap {{ width:100%; border-collapse:collapse; margin-bottom:10px; }}
  table.cap td {{ padding:5px 8px; border-bottom:1px solid #eee; font-size:11.5px; vertical-align:top; }}
  td.cl {{ color:#666; width:46%; }}
  td.cv {{ font-weight:700; }}
  .note {{ font-size:11px; color:#555; background:#f7f9fb; border:1px solid #e2e2e2; border-radius:6px; padding:7px 10px; margin-bottom:10px; }}
  .key {{ border:1px solid #e2e2e2; border-radius:6px; padding:8px 10px; }}
  .keyhd {{ font-size:9.5px; text-transform:uppercase; letter-spacing:.04em; color:#888; font-weight:700; margin-bottom:5px; }}
  .ck {{ font-size:10.5px; margin:2px 0; }}
  .sw {{ display:inline-block; width:14px; height:10px; border:2px solid #000; margin-right:7px; vertical-align:baseline; }}
  .howto {{ margin-top:12px; border:1px solid #ddd; border-radius:7px; padding:10px 13px; background:#f7f9fb; font-size:11px; line-height:1.5; }}
  .howto b {{ color:{branding.RED}; }}
  .jobgrid {{ display:flex; flex-wrap:wrap; gap:7px 26px; margin:10px 0 8px; }}
  .jobgrid div span {{ display:block; text-transform:uppercase; letter-spacing:.03em; color:#999; font-size:8.5px; font-weight:700; }}
  .jobgrid div b {{ font-size:12.5px; }}
  .intro {{ font-size:11.5px; color:#444; margin:5px 0 9px; }}
  table.summary {{ width:100%; border-collapse:collapse; margin-bottom:10px; }}
  table.summary th {{ background:{branding.RED}; color:#fff; text-align:left; padding:5px 9px; font-size:9.5px; text-transform:uppercase; }}
  table.summary td {{ padding:3px 9px; border-bottom:1px solid #eaeaea; font-size:10.5px; }}
  table.summary tr:nth-child(even) td {{ background:#fafafa; }}
  .ov {{ color:{branding.RED}; font-weight:700; font-size:9.5px; }}
  footer {{ margin-top:14px; border-top:1px solid #ddd; padding-top:6px; display:flex; justify-content:space-between; color:#999; font-size:9px; }}
  {branding.BRAND_CSS}
"""
HEAD = '<!doctype html><html><head><meta charset="utf-8"><style>' + CSS + '</style></head><body>'
FOOT = '</body></html>'


def build_templates_html(spec):
    """The whole client-template document: a cover + one page per panel."""
    panels = spec.get("panels", [])
    over = {p.get("name") for p in oversized_panels(spec)}
    pages = len(panels) + 1
    parts = [HEAD, _cover_page(spec, panels, over, pages)]
    for i, p in enumerate(panels):
        parts.append(panel_page_html(p, spec, i + 2, pages, oversized=(p.get("name") in over)))
    parts.append(FOOT)
    return "".join(parts)


def single_panel_doc(spec, panel):
    over = {p.get("name") for p in oversized_panels(spec)}
    return HEAD + panel_page_html(panel, spec, 1, 1, oversized=(panel.get("name") in over)) + FOOT


def main():
    args = sys.argv[1:]
    per_panel = "--per-panel" in args
    files = [a for a in args if not a.startswith("--")]
    spec_path = files[0] if files else find_default_spec()
    spec = json.load(open(spec_path))
    spec["__source"] = os.path.basename(spec_path)
    base = os.path.splitext(os.path.basename(spec_path))[0].replace("booth_spec_", "")
    panels = spec.get("panels", [])
    over = oversized_panels(spec)

    hp = os.path.abspath(f"{base}_Client_Templates.html")
    pp = os.path.abspath(f"{base}_Client_Templates.pdf")
    open(hp, "w").write(build_templates_html(spec))
    msg = f"panels: {len(panels)}"
    if over:
        msg += f"  ·  oversized (tile/seam): {', '.join(str(p.get('name')) for p in over)}"
    print(msg)
    print("HTML:", hp)
    if render.html_to_pdf(hp, pp):
        print("PDF :", pp, f"({os.path.getsize(pp)} bytes)")
    else:
        print("PDF step skipped — open the HTML and Print -> Save as PDF.")

    if per_panel:
        made = 0
        for p in panels:
            stem = f"{base}_{re_safe(p.get('name', 'panel'))}_template"
            ph = os.path.abspath(stem + ".html")
            pdf = os.path.abspath(stem + ".pdf")
            open(ph, "w").write(single_panel_doc(spec, p))
            if render.html_to_pdf(ph, pdf):
                made += 1
            try:
                os.remove(ph)
            except OSError:
                pass
        print(f"per-panel PDFs: {made} of {len(panels)}")


if __name__ == "__main__":
    main()
