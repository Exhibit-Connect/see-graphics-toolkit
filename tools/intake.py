#!/usr/bin/env python3
"""
SEE Intake (Phase 2) - turn a 3D handoff into a draft booth-spec JSON.

Goal: capture the "graphic key" the same way every time, so no wall is
missed - regardless of which 3D designer or software produced it.

Handles both handoff styles:
  * PDF export (the placement / dimensions package)
  * native files that are PDF-compatible (.ai, .eps)
  (a true non-PDF native -> export a PDF first; message shown.)

Two passes:
  1. DETERMINISTIC (always, offline): pulls panel names + sizes from the
     text via patterns. This is the reliable floor.
  2. AI ENRICHMENT (optional, --ai): shows an AI model (via OpenRouter) the
     rendered pages to propose finishes / sided / door / keep-clear zones AND to flag any
     printable surface it can SEE that the text pass missed. Needs
     OPENROUTER_API_KEY; without it, the exact request is saved as a
     dry-run so you can run it later.

Output: a draft booth_spec_<job>.json + <job>_intake_review.md (a
completeness checklist a human signs off before it feeds production).

Usage:
    python3 intake.py <handoff.pdf|.ai|.eps> [--job "Name"] [--ai] [--out file.json]
"""
import json, sys, os, re, subprocess, tempfile, shutil

PDF_EXT = (".pdf", ".ai", ".eps")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

SETTINGS = {"scale": 0.5, "bleed_per_side_in": 1.0, "safe_margin_in": 4.0,
            "color_mode": "CMYK / Pantone", "resolution_ppi": {"min": 120, "max": 150},
            "fonts": "convert to outlines",
            "printer_marks": "disabled (no crop/registration/color bars)",
            "submission": ["WeTransfer", "Dropbox", "Adobe Creative Cloud"]}
DOOR_STD = {"panel_w_in": 39.125, "panel_h_in": 95.21, "edge_offset_in": 4.3125,
            "handle": {"dia_in": 2.0, "y_from_floor_in": 37.98},
            "lock": {"dia_in": 1.125, "y_from_floor_in": 41.79}}

# "Name: 78.12" x 173.32""  (overview list) - the most reliable source
PANEL_RE = re.compile(
    r'^[ \t]*([A-Za-z][A-Za-z0-9 ._/&-]*?)[ \t]*:[ \t]*'
    r'([0-9]+(?:\.[0-9]+)?)[ \t]*["”\'’]?[ \t]*[wWhHdD]?[ \t]*[xX][ \t]*'
    r'([0-9]+(?:\.[0-9]+)?)', re.M)
# "Full Scale Trim: 78.12in w x 173.32in h" (per-wall confirmation)
FULLSCALE_RE = re.compile(r'Full Scale Trim:?\s*([0-9.]+)\s*in\s*w\s*x\s*([0-9.]+)\s*in\s*h', re.I)
# bare "39.06" x 134.26"" dims (e.g. the fridge-fabric note)
BARE_DIM_RE = re.compile(r'([0-9]+(?:\.[0-9]+)?)\s*["”]\s*[xX]\s*([0-9]+(?:\.[0-9]+)?)\s*["”]')
# a label line followed by a bare-dim line (per-wall/counter pages) - used to
# cross-check the overview and catch dimension disagreements between pages
SECONDARY_RE = re.compile(
    r'^[ \t]*([A-Za-z][A-Za-z0-9 ._/:&-]{1,30})[ \t]*\n[ \t]*'
    r'([0-9]+(?:\.[0-9]+)?)[ \t]*["”][ \t]*[xX][ \t]*([0-9]+(?:\.[0-9]+)?)[ \t]*["”]', re.M)


def norm_name(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def reconcile(panels, text):
    """Flag panels whose per-wall-page size disagrees with the overview size."""
    sec = {}
    for m in SECONDARY_RE.finditer(text):
        sec.setdefault(norm_name(m.group(1)), (float(m.group(2)), float(m.group(3))))
    out = []
    for p in panels:
        s = sec.get(norm_name(p["name"]))
        if s and s != (p["w"], p["h"]):
            out.append((p["name"], (p["w"], p["h"]), s))
    return out

BLOCK = {"half scale", "full scale trim", "full scale", "template", "output",
         "bleed", "trim", "visual safe area", "note", "notes", "walls", "wall",
         "graphics placement", "version", "prepared by", "details", "soffit", "scale"}


def read_pdf_text(path):
    from pypdf import PdfReader
    r = PdfReader(path)
    pages = [(p.extract_text() or "") for p in r.pages]
    return "\n".join(pages), pages, len(r.pages)


def parse_panels(text):
    found, order, conflicts = {}, [], []
    for m in PANEL_RE.finditer(text):
        name = re.sub(r"\s+", " ", m.group(1)).strip()
        if name.lower() in BLOCK or len(name) > 32:
            continue
        w, h = float(m.group(2)), float(m.group(3))
        if not (1 <= w <= 600 and 1 <= h <= 600):
            continue
        if name in found:
            if found[name] != (w, h):
                conflicts.append((name, found[name], (w, h)))
            continue
        found[name] = (w, h)
        order.append(name)
    return [{"name": n, "w": found[n][0], "h": found[n][1]} for n in order], conflicts


def render_pages(path, n_pages, max_pages=5):
    """Rasterize the first pages to PNG for the AI pass (Ghostscript)."""
    out = []
    for p in range(1, min(n_pages, max_pages) + 1):
        png = os.path.abspath(f"_intake_p{p}.png")
        subprocess.run(["gs", "-q", "-sDEVICE=png16m", "-r80",
                        f"-dFirstPage={p}", f"-dLastPage={p}", "-o", png, path],
                       capture_output=True)
        if os.path.exists(png):
            out.append(png)
    return out


# Standard SEE material vocabulary (mirrors finish_options in the example booth spec).
FINISH_OPTIONS = ["fabric", "sintra", "vinyl", "laminate", "acrylic", "direct print"]

AI_PROMPT = (
    "You are reviewing a trade-show booth GRAPHICS PLACEMENT package (images attached).\n"
    "Return STRICT JSON: {\"panels\":[{\"name\":\"\",\"w\":0,\"h\":0,\"finish\":\"\",\"finish_confidence\":\"low|medium|high\","
    "\"needs_confirm\":true,\"sided\":\"single|double\","
    "\"door\":\"left|right|null\",\"zones\":[{\"label\":\"\",\"w\":0,\"h\":0,\"kind\":\"keepclear|live\"}]}],"
    "\"missing_or_unsure\":[\"\"]}.\n"
    "List EVERY printable panel/graphic with width x height in inches. For EVERY panel you MUST give a best-guess "
    "finish/substrate chosen from this standard material list: " + ", ".join(FINISH_OPTIONS) + ". Never leave finish "
    "blank or \"TBD\" — pick the single most likely material from that list even when the package does not state it. "
    "These finishes are AI BEST GUESSES, not facts: set \"finish_confidence\" (low/medium/high) and keep "
    "\"needs_confirm\" true so a human confirms each one. Also state single vs double sided, whether it has a door "
    "(which side), and any keep-clear areas (TVs, shelves, fridges, glass displays) with sizes.\n"
    "CRITICAL: compare against this text-extracted list and add anything you can SEE that is missing, and note it in "
    "missing_or_unsure:\n__DET__\n"
)


def ai_enrich(path, n_pages, det_panels):
    import ai_client
    imgs = render_pages(path, n_pages)
    prompt = AI_PROMPT.replace("__DET__", json.dumps(det_panels))
    if not ai_client.available():
        payload = ai_client._redacted_payload(prompt, imgs)
        open("_intake_ai_dryrun.json", "w").write(json.dumps(payload, indent=2))
        return {"_status": "dry-run", "_note": "OPENROUTER_API_KEY not set; wrote _intake_ai_dryrun.json",
                "_images": imgs, "_model": ai_client.MODEL}
    try:
        data = ai_client.ask_json(prompt, imgs)
        data["_status"] = "live"; data["_model"] = ai_client.MODEL
        return data
    except Exception as e:
        return {"_status": "error", "_error": str(e)}
    finally:
        for p in imgs:
            try:
                os.remove(p)
            except OSError:
                pass


def ai_finish_guesses(ai, panels):
    """Map text-pass panel name -> AI best-guess finish, for panels the AI proposed
    a usable (non-blank, non-TBD) finish for. Safe on dry-run/error/text-only AI
    payloads (returns {}). These are guesses a human must still confirm."""
    if not isinstance(ai, dict) or ai.get("_status") != "live":
        return {}
    by_norm = {norm_name(p["name"]): p["name"] for p in panels}
    out = {}
    for ap in ai.get("panels", []) or []:
        fin = str(ap.get("finish", "")).strip()
        if not fin or fin.upper() == "TBD":
            continue
        name = by_norm.get(norm_name(str(ap.get("name", ""))))
        if name and name not in out:
            out[name] = fin
    return out


def build_review(job, src, panels, conflicts, fullscale, extras, ai):
    lines = [f"# Intake review — {job}", "",
             f"Source handoff: `{os.path.basename(src)}`  ·  **DRAFT — a person must confirm this before it feeds production.**", "",
             f"## Panels found by the text pass ({len(panels)})", "",
             "| Panel | W | H |", "|---|---|---|"]
    for p in panels:
        lines.append(f"| {p['name']} | {p['w']}\" | {p['h']}\" |")
    lines += ["", f"Per-wall \"Full Scale Trim\" confirmations found: {len(fullscale)}", ""]
    lines += ["## Confirm / fill before use", ""]
    finish_line = "**Finish / substrate** per panel (text pass can't see it — currently TBD)"
    ai_finishes = ai_finish_guesses(ai, panels) if ai else {}
    if ai_finishes:
        guesses = ", ".join(f"{n}: {g}" for n, g in ai_finishes.items())
        finish_line = f"**Finish / substrate** per panel ({guesses}) — AI best-guess, CONFIRM"
    todo = [finish_line,
            "**Single vs double-sided** per structure (defaulted to single)",
            "**Door** — which wall + side (lift hardware from the 1Mx8 templates)",
            "**Keep-clear zones** — TVs, shelves, fridges, displays: size + position",
            "**Due date**"]
    for t in todo:
        lines.append(f"- [ ] {t}")
    if conflicts:
        lines += ["", "### ⚠ Dimension conflicts (same panel, two sizes)"]
        for n, a, b in conflicts:
            lines.append(f"- **{n}**: {a[0]}x{a[1]} vs {b[0]}x{b[1]} — pick one")
    if extras:
        lines += ["", "### Notes pulled from the package"]
        for e in extras:
            lines.append(f"- {e}")
    lines += ["", "## AI enrichment pass"]
    if ai is None:
        lines.append("- not run (use `--ai`).")
    elif ai.get("_status") == "dry-run":
        lines.append(f"- **dry-run** (no API key). Model `{ai.get('_model')}`. Request written to `_intake_ai_dryrun.json` — set `OPENROUTER_API_KEY` and re-run with `--ai` to execute.")
    elif ai.get("_status") == "live":
        lines.append(f"- **ran live** with `{ai.get('_model')}`. Proposed {len(ai.get('panels', []))} panels; "
                     f"missing/unsure: {', '.join(ai.get('missing_or_unsure', []) or ['none'])}. See `_intake.ai` in the JSON.")
    else:
        lines.append(f"- error: {ai.get('_error')}")
    return "\n".join(lines) + "\n"


def main():
    args = sys.argv[1:]
    use_ai = "--ai" in args
    args = [a for a in args if a != "--ai"]
    job, out = None, None
    files = []
    i = 0
    while i < len(args):
        if args[i] == "--job":
            job = args[i + 1]; i += 2
        elif args[i] == "--out":
            out = args[i + 1]; i += 2
        else:
            files.append(args[i]); i += 1
    if not files:
        print("usage: python3 intake.py <handoff.pdf|.ai|.eps> [--job \"Name\"] [--ai] [--out file.json]")
        return
    src = files[0]
    ext = os.path.splitext(src)[1].lower()
    if ext not in PDF_EXT:
        print(f"'{ext}' is not PDF-compatible. Export a PDF from the 3D/design tool and re-run on that.\n"
              f"(PDF, .ai and .eps work directly.)")
        return

    text, pages, n = read_pdf_text(src)
    panels, conflicts = parse_panels(text)
    conflicts += reconcile(panels, text)   # overview vs per-wall pages

    fullscale = FULLSCALE_RE.findall(text)
    extras = []
    if re.search(r"hanging sign", text, re.I):
        extras.append("Hanging Sign present — uses a vendor template (exclude from generation).")
    mfab = re.search(r"fabric", text, re.I)
    if re.search(r"fridge|fabric", text, re.I):
        local = BARE_DIM_RE.findall(text[mfab.start():mfab.start() + 220]) if mfab else []
        extras.append("Interior fridge-display fabric referenced" + (f" (sizes by the note: {', '.join(a + 'x' + b for a, b in local)})" if local else "") + " — confirm + add fabric panels.")
    if re.search(r"\bshel(f|ves|fs)\b", text, re.I):
        extras.append("Shelves referenced ('shelfs can be placed on this wall') — confirm wall, size, position; add as keep-clear zones.")
    if re.search(r"\bdoor\b", text, re.I):
        extras.append("Door referenced — confirm which wall and side.")

    job = job or "Untitled job (from " + os.path.basename(src) + ")"
    ai = ai_enrich(src, n, panels) if use_ai else None

    spec = {
        "_about": "DRAFT booth spec produced by intake.py from a 3D handoff. CONFIRM before production. "
                  "Feeds SEE_Wall_Template_Generator.jsx, generate_spec_packet.py and proofer.py.",
        "job": {"name": job, "due_date": "TBD"},
        "settings": SETTINGS, "door_standard": DOOR_STD,
        "panels": [dict(name=p["name"], w=p["w"], h=p["h"], finish="TBD", sided="single") for p in panels],
        "pending_inputs": ["finish/substrate per panel", "double-sided structures",
                           "door wall + side", "TV/shelf/fixture zones (size + position)", "due date"],
        "_intake": {"source": os.path.basename(src), "pages": n,
                    "panels_found": len(panels), "fullscale_confirms": len(fullscale),
                    "conflicts": [{"name": c[0], "a": c[1], "b": c[2]} for c in conflicts],
                    "notes": extras, "ai": ai},
    }
    base = re.sub(r"[^A-Za-z0-9]+", "_", job).strip("_")
    out = out or f"booth_spec_{base}_DRAFT.json"
    json.dump(spec, open(out, "w"), indent=2)
    review = f"{base}_intake_review.md"
    open(review, "w").write(build_review(job, src, panels, conflicts, fullscale, extras, ai))

    print(f"Read {n} pages of {os.path.basename(src)}")
    print(f"Panels found (text pass): {len(panels)}  ->  " + ", ".join(p['name'] for p in panels))
    if conflicts:
        print(f"  ⚠ {len(conflicts)} dimension conflict(s): " + "; ".join(f"{c[0]} {c[1]}!={c[2]}" for c in conflicts))
    if ai:
        print(f"  AI pass: {ai.get('_status')}" + (f" ({ai.get('_note')})" if ai.get('_note') else ""))
    print(f"Draft spec : {out}")
    print(f"Review     : {review}")


if __name__ == "__main__":
    main()
