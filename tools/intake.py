#!/usr/bin/env python3
"""
SEE Intake (Phase 2) - turn a 3D handoff into a draft booth-spec JSON.

Goal: capture the "graphic key" the same way every time, so no wall is
missed - regardless of which 3D designer or software produced it.

Handles both handoff styles:
  * PDF export (the placement / dimensions package)
  * native files that carry PDF-compatible content (.ai, and .eps saved with a
    PDF stream). A PostScript-only .eps/.ai cannot be parsed - the tool says so
    and asks for a PDF export instead of dumping a traceback.

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
        [--max-pages N] [--force]

All pages are rendered/OCR'd by default (--max-pages caps it, and the skip is
disclosed). Any page Ghostscript/tesseract could not process is reported in the
printed summary, the review's "Tool warnings" section and _intake.warnings -
never silently dropped. Re-running refuses to overwrite an existing draft or
review (a designer may have hand-confirmed them) unless --force, or --out for
an explicitly named draft.
"""
import argparse, json, sys, os, re, subprocess, tempfile, shutil

PDF_EXT = (".pdf", ".ai", ".eps")

SETTINGS = {"scale": 0.5, "bleed_per_side_in": 1.0, "safe_margin_in": 4.0,
            "color_mode": "CMYK / Pantone", "resolution_ppi": {"min": 120, "max": 150},
            "fonts": "convert to outlines",
            "printer_marks": "disabled (no crop/registration/color bars)",
            "submission": ["WeTransfer", "Dropbox", "Adobe Creative Cloud"]}
DOOR_STD = {"panel_w_in": 39.125, "panel_h_in": 95.21, "edge_offset_in": 4.3125,
            "handle": {"dia_in": 2.0, "y_from_floor_in": 37.98},
            "lock": {"dia_in": 1.125, "y_from_floor_in": 41.79}}

# "Name: 78.12" x 173.32""  (overview list) - the most reliable source.
# Captures the optional unit letter on BOTH numbers ('96"h x 48"w' is
# height-first - discarding the letters used to transpose those dims).
PANEL_RE = re.compile(
    r'^[ \t]*([A-Za-z][A-Za-z0-9 ._/&-]*?)[ \t]*:[ \t]*'
    r'([0-9]+(?:\.[0-9]+)?)[ \t]*["”\'’]?[ \t]*([wWhHdD])?[ \t]*[xX][ \t]*'
    r'([0-9]+(?:\.[0-9]+)?)[ \t]*["”\'’]?[ \t]*([wWhHdD])?', re.M)
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
    """Panels from overview lines ('Name: W x H'). Returns (panels, conflicts).
    Conflict entries are (name, (w,h), (w,h)) tuples for two-sizes disagreements
    or plain strings for parsing notes (e.g. contradictory unit labels). Panels
    are deduped on norm_name so 'Wall A'/'WALL A' is ONE panel (first-seen
    display name kept); a repeat at a different size is a conflict, not a
    second panel. '96\"h x 48\"w' honors the unit letters (w=48, h=96)."""
    found, order, conflicts = {}, [], []
    for m in PANEL_RE.finditer(text):
        name = re.sub(r"\s+", " ", m.group(1)).strip()
        if name.lower() in BLOCK or len(name) > 32:
            continue
        w, h = float(m.group(2)), float(m.group(4))
        u1, u2 = (m.group(3) or "").lower(), (m.group(5) or "").lower()
        if u1 == "h" and u2 == "w":
            w, h = h, w
        elif u1 and u1 == u2 and u1 in ("w", "h"):
            conflicts.append(f"{name}: contradictory unit labels (both marked '{u1}') — "
                             f"kept {w} x {h} as written; confirm which is width")
        if not (1 <= w <= 600 and 1 <= h <= 600):
            continue
        key = norm_name(name)
        if key in found:
            if found[key][1] != (w, h):
                conflicts.append((found[key][0], found[key][1], (w, h)))
            continue
        found[key] = (name, (w, h))
        order.append(key)
    return [{"name": found[k][0], "w": found[k][1][0], "h": found[k][1][1]} for k in order], conflicts


# "Graphic Key" table rows: `C 107.325"w x 153.8125"h`, `H1-H2 39.0625"w x 153.8125"h`.
# This is how real handoffs print sizes (a key on the floor plan); recovered via OCR.
KEY_RE = re.compile(
    r'^[ \t]*([A-Za-z0-9]+(?:[ \t]*-[ \t]*[A-Za-z0-9]+)?)[ \t]+'
    r'([0-9]+(?:\.[0-9]+)?)[ \t]*["”]?[ \t]*[wW][ \t]*[xX][ \t]*'
    r'([0-9]+(?:\.[0-9]+)?)[ \t]*["”]?[ \t]*[hH]', re.M)


def _expand_range_label(label):
    """Expand a graphic-key range label into every panel it names.
    Returns (names, note): 'H1-H4' -> [H1,H2,H3,H4] (a split on '-' used to
    keep only the endpoints, silently dropping H2/H3 from the draft); 'C-E' ->
    [C,D,E]. An unexpandable mixed form keeps both endpoints and returns a
    review note so a human checks for panels in between. Pure."""
    if "-" not in label:
        return [label.strip()], None
    a, b = (p.strip() for p in re.split(r"\s*-\s*", label, maxsplit=1))
    ma, mb = re.match(r"^([A-Za-z]*)(\d+)$", a), re.match(r"^([A-Za-z]*)(\d+)$", b)
    if ma and mb and mb.group(1) in (ma.group(1), ""):     # H1-H4 or H1-4
        lo, hi = int(ma.group(2)), int(mb.group(2))
        if lo <= hi <= lo + 100:
            pad = len(ma.group(2)) if ma.group(2).startswith("0") else 0
            return [f"{ma.group(1)}{str(i).zfill(pad)}" for i in range(lo, hi + 1)], None
    if len(a) == 1 and len(b) == 1 and a.isalpha() and b.isalpha() and ord(a) <= ord(b):
        return [chr(i) for i in range(ord(a), ord(b) + 1)], None   # C-E -> C,D,E
    return [a, b], (f"range '{label}' could not be fully expanded — kept only the endpoints "
                    f"{a} and {b}; check the key for panels between them")


def parse_graphic_key(text):
    """Parse a 'Graphic Key' table (label + W\"w x H\"h) — how real handoffs print
    per-graphic sizes on the floor plan, recovered via OCR. Expands ranges like
    'H1-H4' or 'C-E' into the FULL run of panels sharing that size. Returns
    (panels, conflicts) — same shapes as parse_panels: panels deduped on
    norm_name in order; a repeated label at a different size is a conflict
    tuple, an unexpandable range a conflict note string. Deterministic + pure
    (same text in -> same panels out), which is the whole point: no run-to-run
    variance."""
    found, order, conflicts = {}, [], []
    for m in KEY_RE.finditer(text):
        w, h = float(m.group(2)), float(m.group(3))
        if not (1 <= w <= 600 and 1 <= h <= 600):
            continue
        names, note = _expand_range_label(m.group(1))
        if note:
            conflicts.append(note)
        for name in names:
            if not name:
                continue
            key = norm_name(name)
            if key in found:
                if found[key][1] != (w, h):
                    conflicts.append((found[key][0], found[key][1], (w, h)))
                continue
            found[key] = (name, (w, h))
            order.append(key)
    return [{"name": found[k][0], "w": found[k][1][0], "h": found[k][1][1]} for k in order], conflicts


# Render DPIs. High enough that fine printed dimension labels (e.g. 39.0625") are
# legible, not just shapes. Graphic-key text is often OUTLINED/vector — not
# selectable and easy to lose at low DPI — so both passes render high. OCR is the
# deterministic, primary size reader; the AI pass is the completeness backstop.
AI_RENDER_DPI = 150
OCR_RENDER_DPI = 300

GS = shutil.which("gs")                # Ghostscript - rasterizes pages for the AI/OCR passes
TESSERACT = shutil.which("tesseract")  # deterministic OCR engine, if installed


def _stderr_tail(proc, n=200):
    """Last chars of a subprocess result's stderr, decoded safely ('' if none)."""
    s = getattr(proc, "stderr", None) or b""
    if isinstance(s, bytes):
        s = s.decode("utf-8", "replace")
    s = s.strip()
    return s[-n:]


def _page_cap(n_pages, max_pages, what):
    """(last_page, warnings) for a page cap. Default = ALL pages (a capped read
    used to silently drop pages 6+/9+ - a missed wall). When a cap applies, the
    skip is stated honestly so it lands in the review + spec warnings."""
    if max_pages is None or max_pages >= n_pages:
        return n_pages, []
    return max_pages, [f"{what}: read {max_pages} of {n_pages} pages (--max-pages {max_pages}); "
                       f"skipped pages {max_pages + 1}-{n_pages}"]


def render_pages(path, n_pages, max_pages=None, run=None):
    """Rasterize pages to PNG for the AI pass (Ghostscript), at AI_RENDER_DPI so
    the model can read small dimension labels, not just shapes.

    Returns (image_paths, warnings). Every page goes to a UNIQUE path inside a
    per-run temp dir (a fixed cwd name let a stale or concurrent job's page be
    sent to the AI), and a page counts only when gs exited 0 AND created the
    file. Failed pages are recorded in `warnings` (page number + stderr tail) -
    never silently dropped. `run` is injectable for tests."""
    run = run or subprocess.run
    if not GS:
        return [], ["Ghostscript not installed — AI/OCR page rendering skipped "
                    "(no pages could be rasterized)"]
    last, warnings = _page_cap(n_pages, max_pages, "AI page render")
    tmpdir = tempfile.mkdtemp(prefix="_intake_render_")
    out = []
    for p in range(1, last + 1):
        png = os.path.join(tmpdir, f"p{p}.png")
        r = run([GS, "-q", "-sDEVICE=png16m", f"-r{AI_RENDER_DPI}",
                 f"-dFirstPage={p}", f"-dLastPage={p}", "-o", png, path],
                capture_output=True)
        if r.returncode != 0 or not os.path.exists(png):
            tail = _stderr_tail(r)
            warnings.append(f"page {p}: Ghostscript render failed (rc {r.returncode})"
                            + (f": {tail}" if tail else ""))
            continue
        out.append(png)
    if not out:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return out, warnings


def ocr_pages(path, n_pages, max_pages=None, run=None):
    """Render pages to high-res PNG and OCR them with tesseract (DETERMINISTIC) - the
    fallback when a handoff has no extractable text (a visual deck). Returns
    (concatenated_text, warnings). Same image -> same text every run, so panels
    recovered from this don't vary run-to-run (unlike the AI). Page PNGs live in a
    per-run temp dir (removed in a finally); a failed gs or tesseract page is
    recorded in `warnings` instead of silently vanishing ('no wall is missed').
    `run` is injectable for tests."""
    run = run or subprocess.run
    if not TESSERACT:
        return "", ["tesseract not installed — OCR of the visual handoff skipped"]
    if not GS:
        return "", ["Ghostscript not installed — AI/OCR page rendering skipped "
                    "(no pages could be rasterized)"]
    last, warnings = _page_cap(n_pages, max_pages, "OCR")
    tmpdir = tempfile.mkdtemp(prefix="_intake_ocr_")
    out = []
    try:
        for p in range(1, last + 1):
            png = os.path.join(tmpdir, f"ocr_p{p}.png")
            r = run([GS, "-q", "-sDEVICE=png16m", f"-r{OCR_RENDER_DPI}",
                     f"-dFirstPage={p}", f"-dLastPage={p}", "-o", png, path],
                    capture_output=True)
            if r.returncode != 0 or not os.path.exists(png):
                tail = _stderr_tail(r)
                warnings.append(f"page {p}: Ghostscript render failed (rc {r.returncode})"
                                + (f": {tail}" if tail else ""))
                continue
            try:
                t = run([TESSERACT, png, "stdout"], capture_output=True, text=True)
            except OSError as e:
                warnings.append(f"page {p}: tesseract failed: {e}")
                continue
            if t.returncode != 0:
                tail = _stderr_tail(t)
                warnings.append(f"page {p}: tesseract failed (rc {t.returncode})"
                                + (f": {tail}" if tail else ""))
                continue
            out.append(t.stdout or "")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return "\n".join(out), warnings


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


def ai_enrich(path, n_pages, det_panels, max_pages=None):
    import ai_client
    imgs, warnings = render_pages(path, n_pages, max_pages)
    tmpdirs = {os.path.dirname(p) for p in imgs}
    try:
        prompt = AI_PROMPT.replace("__DET__", json.dumps(det_panels))
        if not ai_client.available():
            # json_mode=True mirrors the live ask_json call below - the dry-run
            # is documented as "the exact request", so it must carry response_format
            payload = ai_client._redacted_payload(prompt, imgs, json_mode=True)
            with open("_intake_ai_dryrun.json", "w") as f:
                f.write(json.dumps(payload, indent=2))
            return {"_status": "dry-run", "_note": "OPENROUTER_API_KEY not set; wrote _intake_ai_dryrun.json",
                    "_pages_rendered": len(imgs), "_model": ai_client.MODEL, "_warnings": warnings}
        try:
            data = ai_client.ask_json(prompt, imgs)
            data["_status"] = "live"; data["_model"] = ai_client.MODEL; data["_warnings"] = warnings
            return data
        except Exception as e:
            return {"_status": "error", "_error": str(e), "_warnings": warnings}
    finally:
        # the finally covers the dry-run return too - no page PNG survives the run
        for p in imgs:
            try:
                os.remove(p)
            except OSError:
                pass
        for d in tmpdirs:
            shutil.rmtree(d, ignore_errors=True)


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


def build_review(job, src, panels, conflicts, fullscale, extras, ai, panel_source="text", undimensioned=None,
                 warnings=None):
    undimensioned = undimensioned or []
    warnings = warnings or []
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
        lines += ["", "### ⚠ Dimension conflicts (same panel, two sizes) / parsing notes"]
        for c in conflicts:
            if isinstance(c, str):
                lines.append(f"- {c}")
            else:
                n, a, b = c
                lines.append(f"- **{n}**: {a[0]}x{a[1]} vs {b[0]}x{b[1]} — pick one")
    if extras:
        lines += ["", "### Notes pulled from the package"]
        for e in extras:
            lines.append(f"- {e}")
    if warnings:
        lines += ["", "### Tool warnings",
                  "_Pages the render/OCR tools could NOT process — the draft may be missing "
                  "panels from these pages; check them by hand._", ""]
        for w in warnings:
            lines.append(f"- ⚠ {w}")
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


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="intake.py",
        description="Turn a 3D handoff (PDF / PDF-compatible .ai/.eps) into a draft "
                    "booth-spec JSON + a review checklist a human signs off.")
    ap.add_argument("handoff", help="handoff file (.pdf, .ai or .eps)")
    ap.add_argument("--job", help="job name (default: derived from the file name)")
    ap.add_argument("--out", help="draft spec output path (default: booth_spec_<job>_DRAFT.json)")
    ap.add_argument("--ai", action="store_true", help="run the AI enrichment pass (OpenRouter)")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing draft spec / review file")
    ap.add_argument("--max-pages", type=int, default=None,
                    help="cap AI/OCR page rendering (default: ALL pages; any skip is disclosed)")
    a = ap.parse_args(argv)
    use_ai, job, out, max_pages = a.ai, a.job, a.out, a.max_pages

    src = a.handoff
    ext = os.path.splitext(src)[1].lower()
    if ext not in PDF_EXT:
        print(f"'{ext}' is not PDF-compatible. Export a PDF from the 3D/design tool and re-run on that.\n"
              f"(PDF, and .ai/.eps saved with PDF content, work directly.)")
        sys.exit(2)

    # Refuse to clobber a draft/review a designer may have hand-confirmed.
    job_name = job or "Untitled job (from " + os.path.basename(src) + ")"
    base = re.sub(r"[^A-Za-z0-9]+", "_", job_name).strip("_")
    out = out or f"booth_spec_{base}_DRAFT.json"
    review = f"{base}_intake_review.md"
    if os.path.exists(out) and not (a.out or a.force):
        print(f"{out} exists (it may carry hand-confirmed edits) — pass --out for a new "
              f"path or --force to overwrite.")
        sys.exit(1)
    if os.path.exists(review) and not a.force:
        print(f"{review} exists (it may carry hand-confirmed sign-offs) — pass --force to overwrite.")
        sys.exit(1)

    try:
        text, pages, n = read_pdf_text(src)
    except Exception as e:                      # pypdf.errors.PdfReadError + anything else
        if ext in (".eps", ".ai"):
            print(f"Could not parse '{os.path.basename(src)}' as a PDF ({type(e).__name__}: {e}).\n"
                  f"This {ext} appears to be PostScript-only — export a PDF from the 3D/design "
                  f"tool and re-run on that.")
        else:
            print(f"Could not read '{os.path.basename(src)}' as a PDF ({type(e).__name__}: {e}).\n"
                  f"Export a fresh PDF from the 3D/design tool and re-run on that.")
        sys.exit(2)
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

    job = job_name
    warnings = []
    ai = ai_enrich(src, n, panels, max_pages) if use_ai else None
    if isinstance(ai, dict):
        warnings += ai.get("_warnings", [])

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
        ocr_panels, ocr_conflicts = [], []
        ocr_text, ocr_warnings = ocr_pages(src, n, max_pages)
        warnings += ocr_warnings
        if ocr_text:
            ocr_panels, ocr_conflicts = parse_graphic_key(ocr_text)
            if not ocr_panels:
                ocr_panels, ocr_conflicts = parse_panels(ocr_text)
        if ocr_panels:
            # keep what the producing parser flagged + cross-check the OCR text's
            # per-wall pages, exactly like the text pass (conflicts were discarded here)
            conflicts += ocr_conflicts + reconcile(ocr_panels, ocr_text)
            spec_panels = [dict(name=p["name"], w=p["w"], h=p["h"], finish="TBD", sided="single",
                                needs_confirm=True, _source="OCR of graphic key (CONFIRM label + size)")
                           for p in ocr_panels]
            panel_source = "ocr"
        else:
            seeded, undimensioned = ai_seed_panels(ai)
            if seeded:
                spec_panels, panel_source = seeded, "ai-vision"

    pending = ["job number (TBD — set it so proofs join the dashboard by number)",
               "finish/substrate per panel", "double-sided structures",
               "door wall + side", "TV/shelf/fixture zones (size + position)", "due date"]
    if undimensioned:
        pending.insert(0, "DIMENSIONS for AI-seen surfaces with no printed size (measure/confirm — do NOT guess): "
                       + ", ".join(undimensioned))

    spec = {
        "_about": "DRAFT booth spec produced by intake.py from a 3D handoff. CONFIRM before production. "
                  "Feeds SEE_Wall_Template_Generator.jsx, generate_spec_packet.py and proofer.py.",
        "job": {"name": job, "job_number": "TBD", "due_date": "TBD"},
        "settings": SETTINGS, "door_standard": DOOR_STD,
        "panels": spec_panels,
        "pending_inputs": pending,
        "_intake": {"source": os.path.basename(src), "pages": n, "panel_source": panel_source,
                    "panels_found_text": len(panels), "panels_in_draft": len(spec_panels),
                    "ai_undimensioned": undimensioned, "fullscale_confirms": len(fullscale),
                    "conflicts": [{"note": c} if isinstance(c, str) else
                                  {"name": c[0], "a": c[1], "b": c[2]} for c in conflicts],
                    "notes": extras, "warnings": warnings, "ai": ai},
    }
    with open(out, "w") as f:
        json.dump(spec, f, indent=2)
    with open(review, "w") as f:
        f.write(build_review(job, src, spec_panels, conflicts, fullscale, extras, ai,
                             panel_source, undimensioned, warnings))

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
        print(f"  ⚠ {len(conflicts)} dimension conflict(s)/note(s): "
              + "; ".join(c if isinstance(c, str) else f"{c[0]} {c[1]}!={c[2]}" for c in conflicts))
    for w in warnings:
        print(f"  ⚠ tool warning: {w}")
    if ai:
        print(f"  AI pass: {ai.get('_status')}" + (f" ({ai.get('_note')})" if ai.get('_note') else ""))
    print(f"Draft spec : {out}")
    print(f"Review     : {review}")


if __name__ == "__main__":
    main()
