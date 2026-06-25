#!/usr/bin/env python3
"""
SEE wall-template PREVIEW — a quick picture of what the templates will look
like, straight from the booth file. No Adobe Illustrator needed.

The real, production templates come from SEE_Wall_Template_Generator.jsx (run
inside Illustrator). This tool just renders a flat PNG/SVG preview of every
panel — bleed, trim, visual safe area, keep-clear / live zones, and the door —
so you (or a client / leadership) can eyeball the layout without opening AI.

Usage:
    python3 tools/preview_templates.py [booth_spec.json] [--out BASE]

Outputs BASE.svg (always) and BASE.png (via macOS qlmanage when available).
"""
import json, sys, os, glob, math, subprocess, tempfile, shutil, html

PXI = 2.3          # pixels per inch in the preview
COLS = 5           # panels per row
GAP, LBL, PAD, HEADER = 26, 34, 24, 96
C = {"bleed": "#00AEEF", "trim": "#111111", "safe": "#EC008C",
     "keep": "#F7941E", "live": "#39B54A", "door": "#ED1C24"}


def find_default_spec():
    here = os.path.dirname(os.path.abspath(__file__))
    for d in (os.getcwd(), os.path.join(here, "..", "examples"),
              os.path.join(os.getcwd(), "examples"), here):
        hits = sorted(glob.glob(os.path.join(d, "*booth_spec*.json")))
        if hits:
            return hits[0]
    return "booth_spec.json"


def esc(s):
    return html.escape(str(s))


def build_svg(spec):
    st = spec.get("settings", {})
    bleed = st.get("bleed_per_side_in", 1.0)
    safe = st.get("safe_margin_in", 4.0)
    door = spec.get("door_standard", {})
    panels = spec.get("panels", [])
    job = (spec.get("job", {}) or {}).get("name", "Booth")

    def bw(p): return (p["w"] + 2 * bleed) * PXI
    def bh(p): return (p["h"] + 2 * bleed) * PXI

    rows = [panels[i:i + COLS] for i in range(0, len(panels), COLS)]
    colw = [0] * COLS
    for r in rows:
        for j, p in enumerate(r):
            colw[j] = max(colw[j], bw(p))
    colx = [PAD]
    for j in range(COLS):
        colx.append(colx[-1] + colw[j] + GAP)
    rowh = [max(bh(p) for p in r) for r in rows]
    total_w = max(colx[len(r)] for r in rows) if rows else 400
    total_h = HEADER + sum(rh + LBL + GAP for rh in rowh) + PAD

    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_w:.0f}" height="{total_h:.0f}" '
         f'viewBox="0 0 {total_w:.0f} {total_h:.0f}" font-family="Arial, Helvetica, sans-serif">']
    o.append(f'<rect x="0" y="0" width="{total_w:.0f}" height="{total_h:.0f}" fill="#ffffff"/>')
    o.append(f'<text x="{PAD}" y="34" font-size="22" font-weight="700" fill="#111">'
             f'Wall template preview — {esc(job)}</text>')
    # legend
    lx, ly = PAD, 64
    for name, col in [("Bleed", C["bleed"]), ("Trim", C["trim"]), ("Safe area", C["safe"]),
                      ("Keep-clear (fixture/TV/shelf)", C["keep"]), ("Live art", C["live"]),
                      ("Door + holes", C["door"])]:
        o.append(f'<rect x="{lx}" y="{ly-10}" width="16" height="12" fill="none" stroke="{col}" stroke-width="2.5"/>')
        o.append(f'<text x="{lx+22}" y="{ly}" font-size="13" fill="#333">{esc(name)}</text>')
        lx += 34 + len(name) * 7.0

    y = HEADER
    for ri, r in enumerate(rows):
        rh = rowh[ri]
        for j, p in enumerate(r):
            x0 = colx[j]
            pbw, pbh = bw(p), bh(p)
            py = y + LBL + (rh - pbh)            # bottom-align panels in the row
            o.append(f'<text x="{x0:.1f}" y="{y+18:.1f}" font-size="12.5" font-weight="700" fill="#111">{esc(p["name"])}</text>')
            o.append(f'<text x="{x0:.1f}" y="{y+31:.1f}" font-size="10.5" fill="#666">{p["w"]}" × {p["h"]}"</text>')
            bpx, spx = bleed * PXI, safe * PXI
            o.append(f'<rect x="{x0:.1f}" y="{py:.1f}" width="{pbw:.1f}" height="{pbh:.1f}" fill="none" stroke="{C["bleed"]}" stroke-width="2"/>')
            tlx, tty, tw, th = x0 + bpx, py + bpx, p["w"] * PXI, p["h"] * PXI
            tby = tty + th
            o.append(f'<rect x="{tlx:.1f}" y="{tty:.1f}" width="{tw:.1f}" height="{th:.1f}" fill="none" stroke="{C["trim"]}" stroke-width="1.6"/>')
            if p["w"] - 2 * safe > 0 and p["h"] - 2 * safe > 0:
                o.append(f'<rect x="{tlx+spx:.1f}" y="{tty+spx:.1f}" width="{(p["w"]-2*safe)*PXI:.1f}" height="{(p["h"]-2*safe)*PXI:.1f}" '
                         f'fill="none" stroke="{C["safe"]}" stroke-width="1.2" stroke-dasharray="5 4"/>')
            for z in p.get("zones", []):
                col = C["live"] if z.get("kind") == "live" else C["keep"]
                rx, ry = tlx + z["x"] * PXI, tty + (p["h"] - z["y"] - z["h"]) * PXI
                o.append(f'<rect x="{rx:.1f}" y="{ry:.1f}" width="{z["w"]*PXI:.1f}" height="{z["h"]*PXI:.1f}" fill="{col}22" stroke="{col}" stroke-width="1.6" stroke-dasharray="6 4"/>')
                tag = "LIVE" if z.get("kind") == "live" else "keep clear"
                o.append(f'<text x="{rx+4:.1f}" y="{ry+13:.1f}" font-size="8.5" font-weight="700" fill="{col}">{esc(tag)}</text>')
            side = p.get("door")
            if side in ("left", "right") and door:
                dW, dH = door.get("panel_w_in", 39.125) * PXI, door.get("panel_h_in", 95.21) * PXI
                dl = tlx if side == "left" else (tlx + tw - dW)
                dtop = tby - dH
                o.append(f'<rect x="{dl:.1f}" y="{dtop:.1f}" width="{dW:.1f}" height="{dH:.1f}" fill="none" stroke="{C["door"]}" stroke-width="1.8" stroke-dasharray="7 4"/>')
                off = door.get("edge_offset_in", 4.3125) * PXI
                cx = (dl + off) if side == "left" else (dl + dW - off)
                for hole in (door.get("handle", {}), door.get("lock", {})):
                    if hole:
                        cy = tby - hole.get("y_from_floor_in", 38) * PXI
                        o.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{hole.get("dia_in",1)/2*PXI:.1f}" fill="none" stroke="{C["door"]}" stroke-width="1.6"/>')
                o.append(f'<text x="{dl+3:.1f}" y="{dtop+12:.1f}" font-size="8.5" font-weight="700" fill="{C["door"]}">DOOR ({side[0].upper()})</text>')
        y += LBL + rh + GAP
    o.append("</svg>")
    return "\n".join(o), len(panels)


def render_png(svg_path, png_path, width=1600):
    if not shutil.which("qlmanage"):
        return False
    td = tempfile.mkdtemp()
    subprocess.run(["qlmanage", "-t", "-s", str(width), "-o", td, svg_path], capture_output=True)
    produced = os.path.join(td, os.path.basename(svg_path) + ".png")
    ok = os.path.exists(produced)
    if ok:
        shutil.move(produced, png_path)
    shutil.rmtree(td, ignore_errors=True)
    return ok


def main():
    args = sys.argv[1:]
    out_base = None
    files = []
    i = 0
    while i < len(args):
        if args[i] == "--out":
            out_base = args[i + 1]; i += 2
        else:
            files.append(args[i]); i += 1
    spec_path = files[0] if files else find_default_spec()
    spec = json.load(open(spec_path))
    if not out_base:
        out_base = "templates_preview"
    svg_path = os.path.abspath(out_base + ".svg")
    png_path = os.path.abspath(out_base + ".png")
    svg, n = build_svg(spec)
    open(svg_path, "w").write(svg)
    print(f"panels previewed: {n}")
    print("SVG:", svg_path)
    if render_png(svg_path, png_path):
        print("PNG:", png_path)
    else:
        print("PNG: (qlmanage unavailable — open the SVG, or print it to an image)")


if __name__ == "__main__":
    main()
