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
     text via patterns - the reliable floor. If the PDF has no extractable text
     (a visual handoff), it OCRs the pages (tesseract) and parses the graphic
     key the same way - still deterministic + repeatable, NOT an AI guess.
  2. AI ENRICHMENT (optional, --ai): shows an AI model (via OpenRouter) the
     rendered pages to propose finishes / sided / door / keep-clear zones AND to flag any
     printable surface it can SEE that the text pass missed. Needs
     OPENROUTER_API_KEY; without it, the exact request is saved as a
     dry-run so you can run it later.

Output: a draft booth_spec_<job>.json + <job>_intake_review.md (a
completeness checklist a human signs off before it feeds production). When the
text pass finds nothing (a visual handoff), the AI-read panels SEED the draft -
each flagged needs_confirm, with a size only where one is actually printed.

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


# "Graphic Key" table rows: `C 107.325"w x 153.8125"h`, `H1-H2 39.0625"w x 153.8125"h`.
# This is how real handoffs print sizes (a key on the floor plan); recovered via OCR.
KEY_RE = re.compile(
    r'^[ \t]*([A-Za-z0-9]+(?:[ \t]*-[ \t]*[A-Za-z0-9]+)?)[ \t]+'
    r'([0-9]+(?:\.[0-9]+)?)[ \t]*["”]?[ \t]*[wW][ \t]*[xX][ \t]*'
    r'([0-9]+(?:\.[0-9]+)?)[ \t]*["”]?[ \t]*[hH]', re.M)


def parse_graphic_key(text):
    """Parse a 'Graphic Key' table (label + W\"w x H\"h) — how real handoffs print
    per-graphic sizes on the floor plan, recovered via OCR. Expands ranges like
    'H1-H2' or 'C-D' into individual panels sharing that size. Returns
    [{name,w,h}, ...] in order, deduped. Deterministic + pure (same text in -> same
    panels out), which is the whole point: no run-to-run variance."""
    found, order = {}, []
    for m in KEY_RE.finditer(text):
        w, h = float(m.group(2)), float(m.group(3))
        if not (1 <= w <= 600 and 1 <= h <= 600):
            continue
        label = m.group(1)
        parts = [p.strip() for p in re.split(r"\s*-\s*", label)] if "-" in label else [label.strip()]
        for name in parts:
            if name and name not in found:
                found[name] = (w, h)
                order.append(name)
    return [{"name": n, "w": found[n][0], "h": found[n][1]} for n in order]


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


TESSERACT = shutil.which("tesseract")  # deterministic OCR engine, if installed


def ocr_pages(path, n_pages, max_pages=8):
    """Render pages to high-res PNG and OCR them with tesseract (DETERMINISTIC) - the
    fallback when a handoff has no extractable text (a visual deck). Returns the
    concatenated OCR text, or '' if tesseract isn't available. Same image -> same text
    every run, so panels recovered from this don't vary run-to-run (unlike the AI)."""
    if not TESSERACT:
        return ""
    out = []
    for p in range(1, min(n_pages, max_pages) + 1):
        png = os.path.abspath(f"_intake_ocr_p{p}.png")
        subprocess.run(["gs", "-q", "-sDEVICE=png16m", "-r300",
                        f"-dFirstPage={p}", f"-dLastPage={p}", "-o", png, path], capture_output=True)
        if not os.path.exists(png):
            continue
        try:
            r = subprocess.run([TESSERACT, png, "stdout"], capture_output=True, text=True)
            out.append(r.stdout or "")
        except Exception:
            pass
        try:
            os.remove(png)
        except OSError:
            pass
    return "\n".join(out)


# Standard SEE material vocabulary (mirrors finish_options in the example booth spec).
FINISH_OPTIONS = ["fabric", "sintra", "vinyl", "laminate", "acrylic", "direct print"]
# Construction / finishing types. Travis: "anything we use" — an OPEN list; these are the common ones.
FINISHING_TYPES = ["SEG", "Pole Pocket", "Direct Print", "Laminate", "Door", "Corner Post"]

AI_PROMPT = (
    "You are reviewing a trade-show booth GRAPHICS PLACEMENT package (images attached).\n"
    "Return STRICT JSON: {\"panels\":[{\"name\":\"\",\"w\":null,\"h\":null,\"dims_shown\":false,\"finish\":\"\","
    "\"finish_confidence\":\"low|medium|high\",\"finishing_type\":\"\",\"needs_confirm\":true,\"sided\":\"single|double\","
    "\"door\":\"left|right|null\",\"zones\":[{\"label\":\"\",\"w\":null,\"h\":null,\"kind\":\"keepclear|live\"}]}],"
    "\"missing_or_unsure\":[\"\"]}.\n"
    "List EVERY printable panel/graphic you can see.\n"
    "DIMENSIONS — CRITICAL: report \"w\" and \"h\" (inches) ONLY when a size is explicitly printed or labeled for "
    "that panel in the package. If a panel's size is NOT explicitly shown, set \"w\":null, \"h\":null and "
    "\"dims_shown\":false, and DO NOT estimate, infer, calculate, or guess it from the booth size or typical panels — "
    "a wrong printed size is far worse than a blank one. Add every panel whose size is not shown to "
    "\"missing_or_unsure\". Set \"dims_shown\":true only when the size is actually printed in the package.\n"
    "FINISH + FINISHING TYPE (guesses ARE allowed here, unlike sizes): for EVERY panel give a best-guess "
    "finish/substrate from " + ", ".join(FINISH_OPTIONS) + "; and a best-guess finishing/construction type from "
    + ", ".join(FINISHING_TYPES) + " (or another if clearly different). Never leave finish blank — pick the most "
    "likely even if not stated — but set "
    "\"finish_confidence\" (low/medium/high) and keep \"needs_confirm\" true so a human confirms each. Also state "
    "single vs double sided, whether it has a door (which side), and any keep-clear areas (TVs, shelves, fridges, "
    "glass displays).\n"
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


def ai_field_guesses(ai, panels, field):
    """Map text-pass panel name -> AI best-guess for `field` (e.g. 'finish' or
    'finishing_type'), for panels the AI proposed a usable (non-blank, non-TBD)
    value for. Safe on dry-run/error/text-only payloads (returns {}). These are
    guesses a human must still confirm. Pure."""
    if not isinstance(ai, dict) or ai.get("_status") != "live":
        return {}
    by_norm = {norm_name(p["name"]): p["name"] for p in panels}
    out = {}
    for ap in ai.get("panels", []) or []:
        val = str(ap.get(field, "")).strip()
        if not val or val.upper() == "TBD":
            continue
        name = by_norm.get(norm_name(str(ap.get("name", ""))))
        if name and name not in out:
            out[name] = val
    return out


def ai_finish_guesses(ai, panels):
    """AI best-guess finish per text-pass panel name (a human still confirms)."""
    return ai_field_guesses(ai, panels, "finish")


def ai_surface_lines(ai):
    """Markdown bullets for the AI-proposed surfaces (for the review file). Shows a
    panel's size only when the handoff actually printed it (dims_shown + real w/h);
    otherwise flags the size as MISSING - the model is told not to guess sizes, so a
    blank here means 'go get this dimension', not a tool failure. Pure; returns []
    on dry-run/error/text-only payloads."""
    if not isinstance(ai, dict) or ai.get("_status") != "live":
        return []
    lines = []
    for p in ai.get("panels", []) or []:
        name = str(p.get("name", "?")).strip() or "?"
        w, h = p.get("w"), p.get("h")
        shown = p.get("dims_shown") is True and w not in (None, 0, "", "0") and h not in (None, 0, "", "0")
        dims = f'{w}" × {h}"' if shown else "**size NOT in handoff — confirm with the 3D source**"
        fin = str(p.get("finish", "")).strip()
        lines.append(f"- {name}: {dims}" + (f" · finish guess: {fin}" if fin else ""))
    return lines


def ai_seed_panels(ai):
    """When the deterministic text pass finds nothing (a visual/non-text handoff),
    turn the AI vision result into DRAFT booth panels so the handoff still yields a
    usable (flagged) draft instead of an empty one. Returns (panels, undimensioned):
      panels        - dicts {name,w,h,finish,sided,needs_confirm,_source} for AI
                      surfaces whose size is actually SHOWN (dims_shown + numeric w/h);
      undimensioned - names the AI saw with NO printed size (a human measures them;
                      we never invent a size).
    Every seeded panel is marked needs_confirm + _source so it can't be mistaken for
    verified data. Pure; safe on non-live payloads (returns ([], []))."""
    if not isinstance(ai, dict) or ai.get("_status") != "live":
        return [], []
    seeded, undim = [], []
    for p in ai.get("panels", []) or []:
        name = re.sub(r"\s+", " ", str(p.get("name", ""))).strip()
        if not name:
            continue
        w, h = p.get("w"), p.get("h")
        shown = (p.get("dims_shown") is True and isinstance(w, (int, float))
                 and isinstance(h, (int, float)) and w > 0 and h > 0)
        if not shown:
            undim.append(name)
            continue
        sided = str(p.get("sided", "single")).strip().lower()
        seeded.append({"name": name, "w": float(w), "h": float(h),
                       "finish": str(p.get("finish", "")).strip() or "TBD",
                       "finishing_type": str(p.get("finishing_type", "")).strip() or "TBD",
                       "sided": sided if sided in ("single", "double") else "single",
                       "needs_confirm": True, "_source": "AI vision (CONFIRM size + finish)"})
    return seeded, undim


def build_review(job, src, panels, conflicts, fullscale, extras, ai, panel_source="text", undimensioned=None):
    undimensioned = undimensioned or []
    if panel_source == "ai-vision":
        head = f"## Panels — seeded from the AI VISION pass ({len(panels)}) — CONFIRM each, incl. every dimension"
    elif panel_source == "ocr":
        head = f"## Panels — read by DETERMINISTIC OCR of the graphic key ({len(panels)}) — CONFIRM labels + sizes"
    else:
        head = f"## Panels found by the text pass ({len(panels)})"
    lines = [f"# Intake review — {job}", "",
             f"Source handoff: `{os.path.basename(src)}`  ·  **DRAFT — a person must confirm this before it feeds production.**", "",
             head, "",
             "| Panel | W | H |", "|---|---|---|"]
    for p in panels:
        lines.append(f"| {p['name']} | {p['w']}\" | {p['h']}\" |")
    if panel_source == "ai-vision":
        lines += ["", "_Panels + sizes were read by AI from the handoff images — verify every size against the 3D "
                  "source (the AI can misread a digit)._"]
    elif panel_source == "ocr":
        lines += ["", "_Sizes were read by OCR from the handoff's graphic key — repeatable run-to-run, but confirm "
                  "labels (OCR can read a letter like 'I' as '1') and spot-check the sizes against the source._"]
    if undimensioned:
        lines += ["", "### ⚠ Surfaces the AI saw but with NO printed dimensions (measure/confirm — never guess)"]
        lines += [f"- {nm}" for nm in undimensioned]
    lines += ["", f"Per-wall \"Full Scale Trim\" confirmations found: {len(fullscale)}", ""]
    lines += ["## Confirm / fill before use", ""]
    if panel_source == "ai-vision":
        finish_line = "**Finish / substrate** per panel — AI best-guess shown, CONFIRM each"
    else:
        finish_line = "**Finish / substrate** per panel (text pass can't see it — currently TBD)"
        ai_finishes = ai_finish_guesses(ai, panels) if ai else {}
        if ai_finishes:
            guesses = ", ".join(f"{n}: {g}" for n, g in ai_finishes.items())
            finish_line = f"**Finish / substrate** per panel ({guesses}) — AI best-guess, CONFIRM"
    finishing_line = "**Finishing type** per panel (SEG, Pole Pocket, Direct Print, Door, Corner Post…)"
    ft_guesses = ai_field_guesses(ai, panels, "finishing_type") if (ai and panel_source != "ai-vision") else {}
    if ft_guesses:
        finishing_line = ("**Finishing type** per panel ("
                          + ", ".join(f"{n}: {g}" for n, g in ft_guesses.items()) + ") — AI best-guess, CONFIRM")
    todo = [finish_line, finishing_line,
            "**Quantity** per panel (known by the proof stage)",
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
        lines.append(f"- **ran live** with `{ai.get('_model')}`. Proposed {len(ai.get('panels', []))} surface(s); "
                     f"missing/unsure: {', '.join(ai.get('missing_or_unsure', []) or ['none'])}.")
        surfaces = ai_surface_lines(ai)
        if surfaces:
            lines += ["", "**AI-proposed surfaces** (advisory — the model is told NOT to guess sizes, so confirm any "
                      "flagged size against the 3D source before use):"] + surfaces
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

    # The text pass is the reliable floor. If it found NOTHING (a visual / non-text
    # handoff), seed the draft from the AI vision result so the handoff still yields a
    # usable, flagged draft instead of an empty one. AI panels are never trusted blindly:
    # each is needs_confirm, and surfaces with no printed size are listed (never invented).
    panel_source, undimensioned = "text", []
    spec_panels = [dict(name=p["name"], w=p["w"], h=p["h"], finish="TBD", sided="single") for p in panels]
    if not panels:
        # Visual handoff (no extractable text). Prefer DETERMINISTIC OCR of the graphic
        # key — same image -> same panels every run — and fall back to the AI vision pass
        # only if OCR recovers nothing. Either way the panels stay needs_confirm.
        ocr_panels = []
        ocr_text = ocr_pages(src, n)
        if ocr_text:
            ocr_panels = parse_graphic_key(ocr_text) or parse_panels(ocr_text)[0]
        if ocr_panels:
            spec_panels = [dict(name=p["name"], w=p["w"], h=p["h"], finish="TBD", sided="single",
                                needs_confirm=True, _source="OCR of graphic key (CONFIRM label + size)")
                           for p in ocr_panels]
            panel_source = "ocr"
        else:
            seeded, undimensioned = ai_seed_panels(ai)
            if seeded:
                spec_panels, panel_source = seeded, "ai-vision"

    pending = ["finish/substrate per panel", "double-sided structures",
               "door wall + side", "TV/shelf/fixture zones (size + position)", "due date"]
    if undimensioned:
        pending.insert(0, "DIMENSIONS for AI-seen surfaces with no printed size (measure/confirm — do NOT guess): "
                       + ", ".join(undimensioned))

    spec = {
        "_about": "DRAFT booth spec produced by intake.py from a 3D handoff. CONFIRM before production. "
                  "Feeds SEE_Wall_Template_Generator.jsx, generate_spec_packet.py and proofer.py.",
        "job": {"name": job, "due_date": "TBD"},
        "settings": SETTINGS, "door_standard": DOOR_STD,
        "panels": spec_panels,
        "pending_inputs": pending,
        "_intake": {"source": os.path.basename(src), "pages": n, "panel_source": panel_source,
                    "panels_found_text": len(panels), "panels_in_draft": len(spec_panels),
                    "ai_undimensioned": undimensioned, "fullscale_confirms": len(fullscale),
                    "conflicts": [{"name": c[0], "a": c[1], "b": c[2]} for c in conflicts],
                    "notes": extras, "ai": ai},
    }
    base = re.sub(r"[^A-Za-z0-9]+", "_", job).strip("_")
    out = out or f"booth_spec_{base}_DRAFT.json"
    json.dump(spec, open(out, "w"), indent=2)
    review = f"{base}_intake_review.md"
    open(review, "w").write(build_review(job, src, spec_panels, conflicts, fullscale, extras, ai,
                                          panel_source, undimensioned))

    print(f"Read {n} pages of {os.path.basename(src)}")
    if panel_source == "ocr":
        print(f"Text pass: 0 → OCR recovered {len(spec_panels)} panel(s) DETERMINISTICALLY (confirm labels + sizes): "
              + ", ".join(p['name'] for p in spec_panels))
    elif panel_source == "ai-vision":
        print(f"Text pass: 0 panels → seeded {len(spec_panels)} from AI VISION (confirm each): "
              + ", ".join(p['name'] for p in spec_panels))
        if undimensioned:
            print(f"  + {len(undimensioned)} surface(s) seen WITHOUT printed dims (measure): " + ", ".join(undimensioned))
    else:
        print(f"Panels found (text pass): {len(panels)}  ->  " + ", ".join(p['name'] for p in panels))
    if conflicts:
        print(f"  ⚠ {len(conflicts)} dimension conflict(s): " + "; ".join(f"{c[0]} {c[1]}!={c[2]}" for c in conflicts))
    if ai:
        print(f"  AI pass: {ai.get('_status')}" + (f" ({ai.get('_note')})" if ai.get('_note') else ""))
    print(f"Draft spec : {out}")
    print(f"Review     : {review}")


if __name__ == "__main__":
    main()
